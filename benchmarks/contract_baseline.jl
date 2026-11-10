# Julia-side structural validation timing. No speedup expectations.
using Jupy

contract = Jupy.read_contract(joinpath(@__DIR__, "..", "tests", "contracts", "structural.toml"))
function compute(n, matrix)
    return n + 1
end
trusted = Jupy.bind(compute, contract; mode=:trusted)
structural = Jupy.bind(compute, contract; mode=:structural)
@assert trusted === compute

function measure(f)
    for _ in 1:100
        f()
    end
    values = Int[]
    for _ in 1:2000
        start = time_ns()
        f()
        push!(values, time_ns() - start)
    end
    sort!(values)
    return values[cld(length(values), 2)]
end

output = only(ARGS)
mkpath(dirname(output))
open(output, "w") do io
    println(io, "N,direct_median_ns,trusted_median_ns,structural_median_ns")
    for n in (1, 50, 200)
        m = ones(Float64, 3n, 3n)
        @assert structural(n, m) == n + 1
        a = measure(() -> compute(n, m))
        b = measure(() -> trusted(n, m))
        c = measure(() -> structural(n, m))
        println(io, "$n,$a,$b,$c")
    end
end
