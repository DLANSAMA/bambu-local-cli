# Demo recording for README. Regenerate from the repo root with:
#   vhs docs/demo.tape
# Requires: vhs, an installed `plate` in .venv/bin, a reachable printer
# (status is read-only), and side-v2a.stl (or any STL) in the repo root.

Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 400
Set Padding 12

Hide
Type "export PATH=$PWD/.venv/bin:$PATH && clear"
Enter
Show

Type "plate status"
Sleep 500ms
Enter
Sleep 6s

Type "plate slice side-v2a.stl"
Sleep 500ms
Enter
Sleep 6s
