import numpy as np
import paddle
import torch
import unittest
from paddle.fluid.layers.utils import map_structure
import sys
sys.path.append("..")
from utils import TOLERANCE, convert_dtype_to_torch_type

class TestScaleIncubateCase1_FP32(unittest.TestCase):
    def setUp(self):
        self.init_params()
        self.init_threshold()
        self.init_np_inputs_and_dout()
        x_torch, scale_torch, bias_torch, dout_torch = self.gen_torch_inputs_and_dout()
        out_torch, out_grads_torch = self.cal_torch_res(x_torch, scale_torch, bias_torch, self.bias_after_scale, dout_torch)
        del x_torch 
        del scale_torch
        del bias_torch
        del dout_torch 
        self.out_torch = out_torch.cpu().detach().numpy()
        self.out_grads_torch = map_structure(
                                lambda x: x.cpu().numpy(),
                                out_grads_torch,
                            )
        del out_torch, out_grads_torch
        torch.cuda.empty_cache()

    def init_params(self):
        self.np_input_dir = "./inputss_case1.npz"
        self.bias_after_scale = False
        self.dtype = "float32"
        self.save_static_res_path = "./static_develop_res_case1_fp32.npz"
        self.save_eager_res_path = "./eager_develop_res_case1_fp32.npz"
    
    def init_threshold(self):
        self.atol = TOLERANCE[self.dtype]["atol"]
        self.rtol = TOLERANCE[self.dtype]["rtol"]

    def init_np_inputs_and_dout(self):
        np_inputs_array = np.load(self.np_input_dir)
        # get np array from npz file
        self.np_x = np_inputs_array["x"]
        self.np_scale = np_inputs_array["scale"]
        self.np_bias = np_inputs_array["bias"]
        self.np_dout = np_inputs_array["dout"]
        # convert np array dtype
        if self.dtype == "float16":
            self.np_x = self.np_x.astype("float16")
            self.np_dout = self.np_dout.astype("float16")
    
    def gen_torch_inputs_and_dout(self):
        x_torch = torch.tensor(
            self.np_x,
            device='cuda',
            dtype=convert_dtype_to_torch_type(self.dtype)
            if self.dtype != 'bfloat16'
            else torch.float32,
            requires_grad=True,
        )
        scale_torch = self.np_scale
        bias_torch = self.np_bias
        dout_torch = torch.tensor(
            self.np_dout,
            device='cuda',
            dtype=convert_dtype_to_torch_type(self.dtype)
            if self.dtype != 'bfloat16'
            else torch.float32,
            requires_grad=True,
        )
        return x_torch, scale_torch, bias_torch, dout_torch
    
    def gen_eager_inputs_and_dout(self):
        x_eager = paddle.to_tensor(
            self.np_x,
            dtype=self.dtype if self.dtype != 'bfloat16' else "float32",
            place="gpu",
        )
        x_eager.stop_gradient = False
        scale_eager = self.np_scale
        bias_eager = self.np_bias
        dout_eager = paddle.to_tensor(
            self.np_dout,
            dtype=self.dtype if self.dtype != 'bfloat16' else "float32",
            place="gpu",
        )
        dout_eager.stop_gradient = False
        return x_eager, scale_eager, bias_eager, dout_eager

    def gen_static_inputs_and_dout(self):
        x_static = paddle.static.data(
            'x',
            shape=self.np_x.shape,
            dtype=self.dtype if self.dtype != "bfloat16" else "float32",
        )
        x_static.stop_gradient = False
        scale_static = self.np_scale
        bias_static = self.np_bias
        dout_static = paddle.static.data(
            'dout',
            shape=self.np_dout.shape,
            dtype=self.dtype if self.dtype != "bfloat16" else "float32",
        )
        dout_static.stop_gradient = False
        return x_static, scale_static, bias_static, dout_static

    def cal_torch_res(self, x, scale, bias, bias_after_scale, dout):
        if self.dtype == "bfloat16":
            x = x.to(dtype=torch.bfloat16)
            dout = dout.to(dtype=torch.bfloat16)
        if bias_after_scale:
            out = x * scale + bias
        else:
            out = scale * (x + bias)
        out_grads = torch.autograd.grad([out], [x], grad_outputs=[dout])
        if self.dtype == "bfloat16":
            out = out.to(dtype=torch.float32)
        return out, out_grads

    def cal_eager_res(self, x, scale, bias, bias_after_scale, dout):
        if self.dtype == "bfloat16":
            x = paddle.cast(x, dtype="uint16")
            dout = paddle.cast(dout, dtype="uint16")
        out = paddle.scale(x, scale, bias, bias_after_scale)
        out_grads = paddle.grad(
            [out], [x], grad_outputs=[dout]
        )
        if self.dtype == "bfloat16":
            out = paddle.cast(out, dtype="float32")
        return out, out_grads

    def cal_static_res(self, x, scale, bias, bias_after_scale, dout):
        if self.dtype == "bfloat16":
            x = paddle.cast(x, dtype="uint16")
            dout = paddle.cast(dout, dtype="uint16")
        out = paddle.scale(x, scale, bias, bias_after_scale)
        out_grads = paddle.static.gradients(
            [out], [x], target_gradients=[dout]
        )
        if self.dtype == "bfloat16":
            out = paddle.cast(out, dtype="float32")
        return out, out_grads

    def test_eager_accuracy(self):
        # get develop eager res
        develop_res_array = np.load(self.save_eager_res_path)
        out_eager_develop = develop_res_array["out_eager"]
        out_eager_grads_develop = [develop_res_array["out_eager_grad_0"]]

        # calculate incubate eager res
        x_eager, scale_eager, bias_eager, dout_eager = self.gen_eager_inputs_and_dout()
        out_eager, out_grads_eager = self.cal_eager_res(x_eager, scale_eager, bias_eager, self.bias_after_scale, dout_eager)
        out_eager = out_eager.numpy()
        out_grads_eager = map_structure(
                                lambda x: x.numpy(),
                                out_grads_eager,
                            )
        
        # compare incubate eager res with develop eager res
        np.testing.assert_equal(
            out_eager,
            out_eager_develop,
            err_msg=(
                'Incubate: compare scale incubate eager forward res with develop eager forward res failed in %s dtype'
            )
            % self.dtype,
        )
        for idx in range(len(out_grads_eager)):
            np.testing.assert_equal(
                out_grads_eager[idx],
                out_eager_grads_develop[idx],
            err_msg=(
                'Incubate: compare scale incubate eager grad res with develop eager grad res failed in %s dtype'
            )
                % self.dtype,
            )
    
    def test_static_accuracy(self):
        # get develop static res
        develop_res_array = np.load(self.save_static_res_path)
        out_static_develop = develop_res_array["out_static"]
        out_grads_static_develop = [develop_res_array["out_grads_static_0"]]

        # calculate incubate static res
        with paddle.fluid.framework._dygraph_guard(None):
            mp, sp = paddle.static.Program(), paddle.static.Program()
            with paddle.static.program_guard(mp, sp):
                x_static, scale_static, bias_static, dout_static = self.gen_static_inputs_and_dout()
                (out_static, out_grads_static) = self.cal_static_res(
                    x_static,
                    scale_static,
                    bias_static,
                    self.bias_after_scale,
                    dout_static,
                )
        exe = paddle.static.Executor(
            place=paddle.CUDAPlace(0)
        )
        exe.run(sp)
        out = exe.run(
            mp,
            feed={"x": self.np_x, "dout": self.np_dout},
            fetch_list=[out_static] + out_grads_static,
        )
        out_static, out_grads_static = out[0], out[1:]
        paddle.disable_static()
        
        # compare incubate static res with develop static res
        np.testing.assert_equal(
            out_static,
            out_static_develop,
            err_msg=(
                'Incubate: compare scale incubate static forward res with develop static forward res failed in %s dtype'
            )
            % self.dtype,
        )
        for idx in range(len(out_grads_static)):
            np.testing.assert_equal(
                out_grads_static[idx],
                out_grads_static_develop[idx],
            err_msg=(
                'Incubate: compare scale incubate static grad res with develop static grad res failed in %s dtype'
            )
                % self.dtype,
            )

    def test_eager_stability(self):
        x_eager, scale_eager, bias_eager, dout_eager = self.gen_eager_inputs_and_dout()
        out_eager_baseline, out_grads_eager_baseline = self.cal_eager_res(x_eager, scale_eager, bias_eager, self.bias_after_scale, dout_eager)
        out_eager_baseline = out_eager_baseline.numpy()
        out_grads_eager_baseline = map_structure(
                                lambda x: x.numpy(),
                                out_grads_eager_baseline,
                            )
        for i in range(50):
            out_eager, out_grads_eager = self.cal_eager_res(x_eager, scale_eager, bias_eager, self.bias_after_scale, dout_eager)
            out_eager = out_eager.numpy()
            out_grads_eager = map_structure(
                                    lambda x: x.numpy(),
                                    out_grads_eager,
                                )
            np.testing.assert_equal(
                out_eager,
                out_eager_baseline,
                err_msg=(
                    'Develop: paddle.scale eager forward is unstable in %s dtype'
                )
                % self.dtype,
            )
            for idx in range(len(out_grads_eager)):
                np.testing.assert_equal(
                    out_grads_eager[idx],
                    out_grads_eager_baseline[idx],
                    err_msg=(
                        'Develop: paddle.scale eager grad is unstable in %s dtype'
                    )
                    % self.dtype,
                )

    def test_static_stability(self):
        with paddle.fluid.framework._dygraph_guard(None):
            mp, sp = paddle.static.Program(), paddle.static.Program()
            with paddle.static.program_guard(mp, sp):
                x_static, scale_static, bias_static, dout_static = self.gen_static_inputs_and_dout()
                (out_static_pg, out_grads_static_pg) = self.cal_static_res(
                    x_static,
                    scale_static,
                    bias_static,
                    self.bias_after_scale,
                    dout_static,
                )
            exe = paddle.static.Executor(
                place=paddle.CUDAPlace(0)
            )
            exe.run(sp)
            out = exe.run(
                mp,
                feed={"x": self.np_x, "dout": self.np_dout},
                fetch_list=[out_static_pg] + out_grads_static_pg,
            )
            out_static_baseline, out_grads_static_baseline = out[0], out[1:]
            for i in range(50):
                out = exe.run(
                    mp,
                    feed={"x": self.np_x, "dout": self.np_dout},
                    fetch_list=[out_static_pg] + out_grads_static_pg,
                )
                out_static, out_grads_static = out[0], out[1:]
                np.testing.assert_equal(
                    out_static,
                    out_static_baseline,
                    err_msg=(
                        'Develop: paddle.scale static forward is unstable in %s dtype'
                    )
                    % self.dtype,
                )
                for idx in range(len(out_grads_static)):
                    np.testing.assert_equal(
                        out_grads_static[idx],
                        out_grads_static_baseline[idx],
                        err_msg=(
                            'Develop: paddle.scale static grad is unstable in %s dtype'
                        )
                        % self.dtype,
                    )


class TestScaleIncubateCase1_FP16(TestScaleIncubateCase1_FP32):
    def init_params(self):
        self.np_input_dir = "./inputs_case1.npz"
        self.bias_after_scale = False
        self.dtype = "float16"
        self.save_static_res_path = "./static_develop_res_case1_fp16.npy"
        self.save_eager_res_path = "./eager_develop_res_case1_fp16.npy"


class TestScaleIncubateCase1_BFP16(TestScaleIncubateCase1_FP32):
    def init_params(self):
        self.np_input_dir = "./inputs_case1.npz"
        self.bias_after_scale = False
        self.dtype = "bfloat16"
        self.save_static_res_path = "./static_develop_res_case1_bfp16.npy"
        self.save_eager_res_path = "./eager_develop_res_case1_bfp16.npy"


class TestScaleIncubateCase2_FP32(TestScaleIncubateCase1_FP32):
    def init_params(self):
        self.np_input_dir = "./inputs_case2.npz"
        self.bias_after_scale = True
        self.dtype = "float32"
        self.save_static_res_path = "./static_develop_res_case2_fp32.npy"
        self.save_eager_res_path = "./eager_develop_res_case2_fp32.npy"


class TestScaleIncubateCase2_FP16(TestScaleIncubateCase1_FP32):
    def init_params(self):
        self.np_input_dir = "./inputs_case2.npz"
        self.bias_after_scale = True
        self.dtype = "float16"
        self.save_static_res_path = "./static_develop_res_case2_fp16.npy"
        self.save_eager_res_path = "./eager_develop_res_case2_fp16.npy"


class TestScaleIncubateCase2_BFP16(TestScaleIncubateCase1_FP32):
    def init_params(self):
        self.np_input_dir = "./inputs_case2.npz"
        self.bias_after_scale = True
        self.dtype = "bfloat16"
        self.save_static_res_path = "./static_develop_res_case2_bfp16.npy"
        self.save_eager_res_path = "./eager_develop_res_case2_bfp16.npy"


if __name__ == '__main__':
    unittest.main()
