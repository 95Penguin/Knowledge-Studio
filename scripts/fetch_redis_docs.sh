#!/usr/bin/env bash
set -euo pipefail

repo_url="https://github.com/redis/docs.git"
requested_ref="${REDIS_DOCS_REF:-main}"
expected_commit="${REDIS_DOCS_COMMIT:-}"
offline_mode="${REDIS_DOCS_OFFLINE:-0}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
cache_dir="$project_root/.cache/redis-docs"
output_root="$project_root/data/raw/redis-docs"
staging_dir="$output_root/.staging"
source_dir="$output_root/source"
selection_file="$project_root/config/corpus/redis-ops-7.4-v1.paths"
exclusion_file="$project_root/config/corpus/redis-ops-7.4-v1.exclude-patterns"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

require_command git
require_command find
require_command shasum
require_command awk

if [[ ! -f "$selection_file" || ! -f "$exclusion_file" ]]; then
  echo "Corpus selection configuration is missing." >&2
  exit 1
fi

mkdir -p "$(dirname "$cache_dir")" "$output_root"

if [[ ! -d "$cache_dir/.git" ]]; then
  echo "Cloning official Redis docs repository..."
  rm -rf "$cache_dir"
  if ! git clone --filter=blob:none --no-checkout "$repo_url" "$cache_dir"; then
    rm -rf "$cache_dir"
    echo "Clone failed; incomplete cache was removed and no corpus snapshot was changed." >&2
    exit 1
  fi
fi

git -C "$cache_dir" remote set-url origin "$repo_url"
if [[ "$offline_mode" == "1" ]]; then
  if [[ -z "$expected_commit" ]]; then
    echo "REDIS_DOCS_OFFLINE=1 requires REDIS_DOCS_COMMIT." >&2
    exit 1
  fi
  if ! git -C "$cache_dir" cat-file -e "${expected_commit}^{commit}" 2>/dev/null; then
    echo "Commit $expected_commit is not available in the local cache." >&2
    exit 1
  fi
  resolved_commit="$expected_commit"
  echo "Using cached commit without network access: $resolved_commit"
else
  echo "Fetching ref: $requested_ref"
  git -C "$cache_dir" fetch --depth 1 origin "$requested_ref"
  resolved_commit="$(git -C "$cache_dir" rev-parse FETCH_HEAD)"
fi

if [[ -n "$expected_commit" && "$resolved_commit" != "$expected_commit" ]]; then
  echo "Resolved commit $resolved_commit does not match REDIS_DOCS_COMMIT=$expected_commit" >&2
  exit 1
fi

git -C "$cache_dir" checkout --detach --force "$resolved_commit"

if [[ ! -f "$cache_dir/LICENSE" ]]; then
  echo "Upstream LICENSE file is missing; refusing to build corpus." >&2
  exit 1
fi

# Build everything in staging. The current snapshot is replaced only after all
# validation succeeds, so a network/configuration failure cannot leave half a corpus.
rm -rf "$staging_dir"
mkdir -p "$staging_dir/source"

copy_markdown_path() {
  local relative_path="$1"
  local absolute_path="$cache_dir/$relative_path"

  if [[ -f "$absolute_path" && "$absolute_path" == *.md ]]; then
    mkdir -p "$staging_dir/source/$(dirname "$relative_path")"
    cp "$absolute_path" "$staging_dir/source/$relative_path"
  elif [[ -d "$absolute_path" ]]; then
    while IFS= read -r file; do
      local repo_relative="${file#"$cache_dir/"}"
      mkdir -p "$staging_dir/source/$(dirname "$repo_relative")"
      cp "$file" "$staging_dir/source/$repo_relative"
    done < <(find "$absolute_path" -type f -name '*.md' -print | sort)
  else
    echo "Allowlisted path not found upstream: $relative_path" >&2
    return 1
  fi
}

missing_paths=0
while IFS= read -r path; do
  [[ -z "$path" || "$path" == \#* ]] && continue
  if ! copy_markdown_path "$path"; then
    missing_paths=$((missing_paths + 1))
  fi
done < "$selection_file"

if [[ "$missing_paths" -ne 0 ]]; then
  echo "$missing_paths allowlisted path(s) were missing; refusing to publish a partial corpus." >&2
  rm -rf "$staging_dir"
  exit 1
fi

while IFS= read -r pattern; do
  [[ -z "$pattern" || "$pattern" == \#* ]] && continue
  while IFS= read -r excluded; do
    rm -f "$excluded"
  done < <(find "$staging_dir/source" -type f -name '*.md' -print | awk -v p="$pattern" 'BEGIN{IGNORECASE=1} index($0,p)>0')
done < "$exclusion_file"

find "$staging_dir/source" -type d -empty -delete
file_count="$(find "$staging_dir/source" -type f -name '*.md' | wc -l | tr -d ' ')"
if [[ "$file_count" -eq 0 ]]; then
  echo "Selection produced zero Markdown files; refusing to replace snapshot." >&2
  rm -rf "$staging_dir"
  exit 1
fi

cp "$cache_dir/LICENSE" "$staging_dir/LICENSE.upstream"
(
  cd "$staging_dir/source"
  find . -type f -name '*.md' -print0 | sort -z | xargs -0 shasum -a 256
) > "$staging_dir/FILES.sha256"

total_bytes="$(find "$staging_dir/source" -type f -name '*.md' -exec stat -f '%z' {} \; | awk '{sum += $1} END {print sum + 0}')"
license_sha256="$(shasum -a 256 "$cache_dir/LICENSE" | awk '{print $1}')"
retrieved_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

cat > "$staging_dir/CORPUS_MANIFEST.yaml" <<EOF
schema_version: 1
corpus_id: redis-ops-7.4-v1
product: Redis Open Source
target_version: "7.4"
language: en
repository: $repo_url
requested_ref: $requested_ref
resolved_commit: $resolved_commit
retrieved_at_utc: $retrieved_at
license_file: LICENSE.upstream
license_sha256: $license_sha256
selection_file: config/corpus/redis-ops-7.4-v1.paths
exclusion_file: config/corpus/redis-ops-7.4-v1.exclude-patterns
file_count: $file_count
total_bytes: $total_bytes
files_manifest: FILES.sha256
EOF

rm -rf "$source_dir" "$output_root/FILES.sha256" "$output_root/LICENSE.upstream" "$output_root/CORPUS_MANIFEST.yaml"
mv "$staging_dir/source" "$source_dir"
mv "$staging_dir/FILES.sha256" "$output_root/FILES.sha256"
mv "$staging_dir/LICENSE.upstream" "$output_root/LICENSE.upstream"
mv "$staging_dir/CORPUS_MANIFEST.yaml" "$output_root/CORPUS_MANIFEST.yaml"
rmdir "$staging_dir"

echo "Corpus snapshot created successfully."
echo "Commit: $resolved_commit"
echo "Markdown files: $file_count"
echo "Manifest: $output_root/CORPUS_MANIFEST.yaml"
echo "To reproduce exactly: REDIS_DOCS_COMMIT=$resolved_commit ./scripts/fetch_redis_docs.sh"
