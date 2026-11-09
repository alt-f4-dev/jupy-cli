# Opt-in end-to-end smoke test, run via jupy or juuv.
using Jupy
using PythonCall

sys = Jupy.pyimport("sys")
again = Jupy.pyimport("sys")
@assert sys === again

builtins = Jupy.pyimport("builtins")
@assert PythonCall.pyconvert(Int, builtins.len((1, 2, 3))) == 3

println("Julia -> Python: persistent runtime and module caching verified")
