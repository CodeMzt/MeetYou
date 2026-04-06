import subprocess

with open("diff.txt", "w", encoding="utf-8") as f:
    res = subprocess.run(["git", "diff", "docs/interface.md"], capture_output=True, text=True, encoding="utf-8")
    f.write("=== Unstaged ===\n" + res.stdout)
    
    res2 = subprocess.run(["git", "diff", "--staged", "docs/interface.md"], capture_output=True, text=True, encoding="utf-8")
    f.write("\n=== Staged ===\n" + res2.stdout)
    
    res3 = subprocess.run(["git", "log", "-p", "-1", "docs/interface.md"], capture_output=True, text=True, encoding="utf-8")
    f.write("\n=== Last Commit ===\n" + res3.stdout)
