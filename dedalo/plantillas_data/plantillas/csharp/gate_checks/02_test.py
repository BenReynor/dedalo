"""Gate (csharp): `dotnet test`."""
import glob
import shutil
import subprocess

HERRAMIENTA = "[csharp]"


def run(env):
    if not glob.glob("*.sln", root_dir=env.proyecto) and not glob.glob(
            "**/*.csproj", root_dir=env.proyecto, recursive=True):
        env.aviso(f"{HERRAMIENTA} sin .sln/.csproj, se omite")
        return 0
    dotnet = shutil.which("dotnet")
    if not dotnet:
        env.aviso(f"{HERRAMIENTA} dotnet no disponible, se omite")
        return 0
    p = subprocess.run([dotnet, "test", "--nologo", "-v", "q"],
                       cwd=env.proyecto, capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} dotnet test falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} dotnet test OK")
    return 0
