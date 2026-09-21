"""Native TensorRT execution. Only import/use this module in an isolated child."""
from __future__ import annotations


class TensorExecutor:
    def __init__(self, serialized: bytes, device: int):
        import torch
        import tensorrt as trt
        self.torch, self.trt, self.device = torch, trt, device
        torch.cuda.set_device(device)
        self.logger = trt.Logger(trt.Logger.WARNING)
        trt.init_libnvinfer_plugins(self.logger, "")
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(serialized)
        if self.engine is None:
            raise RuntimeError("TensorRT rejected the serialized engine")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("TensorRT could not create an execution context")
        self.names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.inputs = [n for n in self.names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        self.outputs = [n for n in self.names if n not in self.inputs]
        if len(self.inputs) != 1 or len(self.outputs) != 1:
            raise RuntimeError("This component adapter requires exactly one input and one output")

    def __call__(self, value):
        torch, trt = self.torch, self.trt
        types = {trt.float32: torch.float32, trt.float16: torch.float16}
        name = self.inputs[0]
        dtype = types[self.engine.get_tensor_dtype(name)]
        value = value.to(device=f"cuda:{self.device}", dtype=dtype).contiguous()
        if not self.context.set_input_shape(name, tuple(value.shape)):
            raise RuntimeError("TensorRT input is outside the compiled profile")
        if not self.context.set_tensor_address(name, value.data_ptr()):
            raise RuntimeError("TensorRT input binding failed")
        output_name = self.outputs[0]
        shape = tuple(self.context.get_tensor_shape(output_name))
        if any(v <= 0 for v in shape):
            raise RuntimeError("TensorRT returned an unresolved output shape")
        output = torch.empty(shape, device=value.device, dtype=types[self.engine.get_tensor_dtype(output_name)])
        if not self.context.set_tensor_address(output_name, output.data_ptr()):
            raise RuntimeError("TensorRT output binding failed")
        stream = torch.cuda.current_stream(self.device)
        if not self.context.execute_async_v3(stream.cuda_stream):
            raise RuntimeError("TensorRT execution failed")
        stream.synchronize()
        return output


def identity_engine():
    import tensorrt as trt
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    if builder is None:
        raise RuntimeError("TensorRT builder initialization failed")
    # TensorRT 11 is always strongly typed. No removed FP16 builder flags.
    flags = 0 if int(trt.__version__.split(".")[0]) >= 11 else 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
    network = builder.create_network(flags)
    value = network.add_input("input", trt.float32, (1, 4))
    layer = network.add_elementwise(value, value, trt.ElementWiseOperation.SUM)
    layer.get_output(0).name = "output"
    network.mark_output(layer.get_output(0))
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 64 * 1024 * 1024)
    engine = builder.build_serialized_network(network, config)
    if engine is None:
        raise RuntimeError("Synthetic TensorRT engine build failed")
    return bytes(engine)
