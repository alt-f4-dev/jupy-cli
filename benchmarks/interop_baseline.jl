# Direct PythonCall versus Jupy. Times are descriptive; no speedup claims.
using Jupy
using PythonCall

function summarize(f, iterations=200)
    for _ in 1:20
        f()
    end
    samples = Int[]
    for _ in 1:iterations
        start = time_ns()
        f()
        push!(samples, time_ns() - start)
    end
    sort!(samples)
    return (samples[cld(length(samples), 2)], samples[clamp(ceil(Int, 0.9length(samples)), 1, length(samples))])
end

direct = PythonCall.pyimport("math")
jupy_module = Jupy.load("math")
@assert PythonCall.pyconvert(Bool, direct === jupy_module)
metrics = [
    ("cached_module_lookup", summarize(() -> PythonCall.pyimport("math")), summarize(() -> Jupy.load("math"))),
    ("native_bridge_call", summarize(() -> direct.sqrt(9.0)), summarize(() -> jupy_module.sqrt(9.0))),
]
output = only(ARGS)
mkpath(dirname(output))
open(output, "w") do io
    println(io, "operation,direct_median_ns,direct_p90_ns,jupy_median_ns,jupy_p90_ns")
    for (name, d, j) in metrics
        println(io, "$(name),$(d[1]),$(d[2]),$(j[1]),$(j[2])")
    end
end
for (name, d, j) in metrics
    println("$(name): direct median=$(d[1]) ns, Jupy median=$(j[1]) ns")
end
