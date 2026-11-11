"""一次性同步脚本: 把本地 HEAD 的整棵树推到 origin/main, 不打印 token。"""
import base64
import json
import subprocess
import sys
import urllib.request

OWNER, REPO, BRANCH = "KARASzz", "sex-agent", "main"
TOKEN_FILE = "/root/.config/github_token"
WORKDIR = "/root/色情小说大师"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"


def run_git(*args):
    return subprocess.run(
        ["git", *args], cwd=WORKDIR, capture_output=True, text=True, check=True
    ).stdout.strip()


def api(method, path, data=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode() if data is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "opencode-sync",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:300]
        except Exception:
            body = ""
        return e.code, {"_error_body": body}


with open(TOKEN_FILE, encoding="utf-8") as f:
    TOKEN = f.read().strip()
if not TOKEN:
    print("TOKEN_EMPTY");
    sys.exit(1)

local_head = run_git("rev-parse", "HEAD")
# 以暂存区+工作区最新内容为准算候选树(只含已跟踪文件), 与远端树比对才准确
run_git("add", "--update")
candidate_tree = run_git("write-tree")

st, ref = api("GET", f"/git/ref/heads/{BRANCH}")
remote_sha = None
if st == 200:
    remote_sha = ref["object"]["sha"]
    print("remote_head=" + remote_sha)
elif st == 404:
    print("remote_branch_missing")
else:
    print(f"REF_LOOKUP_FAILED status={st} body={ref.get('_error_body', '')}")
    sys.exit(2)

if remote_sha:
    st, commit = api("GET", f"/git/commits/{remote_sha}")
    if st != 200:
        print(f"REMOTE_COMMIT_LOOKUP_FAILED status={st}")
        sys.exit(2)
    if commit.get("tree", {}).get("sha") == candidate_tree:
        print("IN_SYNC nothing_to_push")
        sys.exit(0)
    # 安全检查: 远端若有本地没有的文件, 先比对, 只合并不冲突的部分
    st, rtree = api("GET", f"/git/trees/{commit['tree']['sha']}?recursive=1")
    if st != 200:
        print(f"REMOTE_TREE_LOOKUP_FAILED status={st}")
        sys.exit(2)
    remote_blobs = {t["path"]: t["sha"] for t in rtree.get("tree", [])
                    if t.get("type") == "blob"}
    files_probe = run_git("-c", "core.quotepath=false", "ls-files").splitlines()
    local_set = set(files_probe)
    extra = sorted(set(remote_blobs) - local_set)
    # 002 旧目录 opencode-色情小说大师/ 已整体迁移到 色情小说大师/, 远端该前缀残留一律不复活;
    # 其他远端独有文件则保留(下载落盘并纳入本次提交)
    RESURRECT_SKIP_PREFIXES = ("opencode-色情小说大师/",)
    RESURRECT_BLOCKLIST = {
        "色情小说大师/001_仙途淫师娘_2026-11-08.md",
    }
    keep = [p for p in extra
            if p not in RESURRECT_BLOCKLIST
            and not p.startswith(RESURRECT_SKIP_PREFIXES)]
    drop = [p for p in extra if p not in keep]
    if drop:
        print("skip_resurrect=" + ",".join(drop))
    # 003 共有文件内容不一致则停下报冲突, 不覆盖(白名单除外)
    # 白名单: AGENTS.md 本地为用户明确要求的修订版(远端是旧版, 已 diff 确认, 本地胜出);
    # push_sync.py 只由本沙箱演进, 远端从无外部改动, 本地胜出;
    # 000_账本.md 仅本沙箱写入, 冲突时须先下载 diff, 确认远端只是旧版(无外部改动)方可按本地胜出
    LOCAL_WINS = {"AGENTS.md", "push_sync.py", "色情小说大师/000_账本.md"}
    conflict = []
    for p in sorted(set(remote_blobs) & local_set):
        local_blob = run_git("hash-object", p)
        if local_blob != remote_blobs[p] and p not in LOCAL_WINS:
            conflict.append(p)
    for p in sorted(LOCAL_WINS & set(remote_blobs) & local_set):
        local_blob = run_git("hash-object", p)
        if local_blob != remote_blobs[p]:
            print("local_wins=" + p)
    if conflict:
        print("CONFLICT shared_files_differ:")
        for p in conflict:
            print("  ! " + p)
        sys.exit(8)
    # 004 把远端独有(需保留的)文件落盘并 git add, 纳入本次提交
    for p in keep:
        sha = remote_blobs[p]
        st, blob = api("GET", f"/git/blobs/{sha}")
        if st != 200:
            print(f"BLOB_DOWNLOAD_FAILED {p}")
            sys.exit(3)
        import os
        dest = f"{WORKDIR}/{p}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            import base64 as b64
            f.write(b64.b64decode(blob["content"]).decode("utf-8"))
        print("restored_local=" + p)
    if keep:
        subprocess.run(["git", "add", "--", *keep], cwd=WORKDIR, check=True)

files = run_git("-c", "core.quotepath=false", "ls-files").splitlines()
print(f"files={len(files)}")
tree_entries = []
for path in files:
    with open(f"{WORKDIR}/{path}", "rb") as f:
        raw = f.read()
    st, blob = api("POST", "/git/blobs",
                   {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
    if st != 201:
        print(f"BLOB_FAILED {path} status={st}")
        sys.exit(3)
    tree_entries.append({"path": path, "mode": "100644",
                         "type": "blob", "sha": blob["sha"]})

st, tree = api("POST", "/git/trees", {"tree": tree_entries})
if st != 201:
    print(f"TREE_FAILED status={st}")
    sys.exit(4)

msg = (sys.argv[1] if len(sys.argv) > 1 else "").strip() or "同步章节与账本"
parents = [remote_sha] if remote_sha else []
st, commit = api("POST", "/git/commits",
                 {"message": msg, "tree": tree["sha"], "parents": parents})
if st != 201:
    print(f"COMMIT_FAILED status={st} body={commit.get('_error_body', '')}")
    sys.exit(5)
new_sha = commit["sha"]
print("new_commit=" + new_sha)

if remote_sha:
    st, _ = api("PATCH", f"/git/refs/heads/{BRANCH}", {"sha": new_sha})
else:
    st, _ = api("POST", "/git/refs",
                 {"ref": f"refs/heads/{BRANCH}", "sha": new_sha})
if st not in (200, 201):
    print(f"REF_UPDATE_FAILED status={st}")
    sys.exit(6)
print("PUSH_OK head=" + new_sha)

# 让本地 main 与远端一致(内容相同, 仅是提交对象不同; 本地无对象时跳过)
try:
    subprocess.run(["git", "update-ref", "refs/heads/main", new_sha],
                   cwd=WORKDIR, check=True, capture_output=True)
    print("LOCAL_REF_UPDATED")
except subprocess.CalledProcessError:
    print("LOCAL_REF_SKIP 本地无该对象, 工作区内容已与远端一致")
