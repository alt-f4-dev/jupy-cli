# Opt-in end-to-end smoke test, run via jupy or juuv.
using Jupy
using PythonCall

sys = Jupy.pyimport("sys")
again = Jupy.pyimport("sys")
@assert sys === again

builtins = Jupy.pyimport("builtins")
@assert PythonCall.pyconvert(Int, builtins.len((1, 2, 3))) == 3

caught = false
try
    builtins.eval("1/0")
catch err
    caught = occursin("ZeroDivisionError", sprint(showerror, err))
end
@assert caught "Python exception did not propagate with its error class"

println("Julia -> Python: persistent runtime, module cache and exceptions verified")
