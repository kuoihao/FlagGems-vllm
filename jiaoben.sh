cd /share/project/tle/pr/flash-linear-attention

SRC=perf/gdn2-fused-infer
BASE=$(git merge-base origin/main "$SRC")

GEMS=/share/project/tle/pr/FlagGems-vllm
DST=$GEMS/src/flaggems_vllm/ops/FLA/gdn2_native

mkdir -p "$DST"
touch "$DST/__init__.py"

for f in chunk_fwd.py chunk_intra.py chunk_intra_token_parallel.py wy_fast.py; do
    git show "$BASE:fla/ops/gdn2/$f" > "$DST/$f"
done
