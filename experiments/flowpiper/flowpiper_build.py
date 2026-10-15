"""Build two variants of a Piper VITS voice:
  *.predict.onnx  - original model that also outputs the per-phoneme frame durations it chose
  *.flow.onnx     - same model, but the durations come in as an input you control
"""
import sys, onnx
from onnx import helper, TensorProto

src = sys.argv[1]
m = onnx.load(src)
g = m.graph
ceil = next(n for n in g.node if n.op_type == "Ceil" and n.output[0] == "w_ceil")

# predict variant: expose w_ceil as an extra output
p = onnx.load(src)
p.graph.output.append(helper.make_tensor_value_info("w_ceil", TensorProto.FLOAT, ["batch_size", 1, "phonemes"]))
onnx.save(p, src.replace(".onnx", ".predict.onnx"))

# flow variant: Ceil(predicted) -> Identity(durations input)
g.input.append(helper.make_tensor_value_info("durations", TensorProto.FLOAT, ["batch_size", 1, "phonemes"]))
idx = list(g.node).index(ceil)
g.node.remove(ceil)
g.node.insert(idx, helper.make_node("Identity", ["durations"], ["w_ceil"], name="durations_override"))
onnx.save(m, src.replace(".onnx", ".flow.onnx"))
print("ok")
