#!/usr/bin/env python3

import os
import sys
import shlex
import subprocess
import time
import glob
import re

# Optional color support 
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
    C_OK = Fore.GREEN + Style.BRIGHT
    C_WARN = Fore.YELLOW + Style.BRIGHT
    C_ERR = Fore.RED + Style.BRIGHT
    C_INFO = Fore.CYAN + Style.BRIGHT
    C_RESET = Style.RESET_ALL
except Exception:
    C_OK = C_WARN = C_ERR = C_INFO = C_RESET = ""

def eprint(msg=""):
    print(msg, file=sys.stderr)

def strip_quotes(path: str) -> str:
    path = path.strip()
    if (path.startswith('"') and path.endswith('"')) or (path.startswith("'") and path.endswith("'")):
        return path[1:-1]
    return path

def normalize_path(path: str) -> str:
    path = strip_quotes(path)
    path = os.path.expanduser(path)
    path = os.path.normpath(path)
    return path

def find_gromacs_executable(prefer_mpi: bool):
    candidates = ["gmx_mpi", "gmx"] if prefer_mpi else ["gmx", "gmx_mpi"]
    for c in candidates:
        if shutil_which(c):
            return c
    return candidates[0]

def shutil_which(cmd):
    try:
        import shutil
        return shutil.which(cmd)
    except Exception:
        return None

def print_header():
    print(C_INFO + "="*72 + C_RESET)
    print(C_INFO + "cgui2gmx | CHARMM-GUI to GROMACS Automation & Auditing Tool" + C_RESET)
    print(C_INFO + "Version 1.3 | Designed by karthxk (https://karthxk0.github.io/)" + C_RESET)
    print(C_INFO + "Reminder: update mdp parameters (e.g., nsteps) before running." + C_RESET)
    print(C_INFO + "="*72 + C_RESET)
    print()

def ask_yes_no_numeric(prompt: str, note: str) -> bool:
    print(C_WARN + note + C_RESET)
    while True:
        print(C_INFO + prompt + C_RESET)
        print("  1) Yes")
        print("  2) No")
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            return True
        if choice == "2":
            return False
        print(C_ERR + "Invalid input. Please enter 1 or 2." + C_RESET)

def simple_progress_bar(current, total, width=40):
    frac = current / total
    filled = int(width * frac)
    bar = "[" + "#" * filled + "-" * (width - filled) + "]"
    return f"{bar} {current}/{total}"

def run_command(cmd_list, cwd=None, env=None):
    cmd_display = " ".join(shlex.quote(x) for x in cmd_list)
    print(C_INFO + f"\n>>> Running: {cmd_display}" + C_RESET)
    try:
        proc = subprocess.Popen(cmd_list, cwd=cwd, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1)
    except FileNotFoundError:
        print(C_ERR + f"Executable not found: {cmd_list[0]}. Ensure GROMACS is installed." + C_RESET)
        return 127
    except Exception as e:
        print(C_ERR + f"Failed to start command: {e}" + C_RESET)
        return 1

    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            low = line.lower()
            if "error" in low or "fatal" in low:
                print(C_ERR + line + C_RESET)
            elif "warning" in low:
                print(C_WARN + line + C_RESET)
            else:
                print(line)
    except Exception as e:
        print(C_ERR + f"Error while reading process output: {e}" + C_RESET)
    proc.wait()
    return proc.returncode

def extract_energy(gmx_cmd, edr_file, xvg_file, term, cwd):
    """Silently runs gmx energy to extract a specific thermodynamic term."""
    cmd = [gmx_cmd, "energy", "-f", edr_file, "-o", xvg_file]
    try:
        # Feed the requested term, then an extra newline to exit the prompt
        proc = subprocess.run(cmd, input=f"{term}\n\n", text=True, cwd=cwd,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0 or not os.path.exists(os.path.join(cwd, xvg_file)):
            print(C_WARN + f"    [!] Could not extract {term}. (May not exist in this .edr)" + C_RESET)
            return False
        return True
    except Exception as e:
        print(C_ERR + f"    [!] Error running gmx energy: {e}" + C_RESET)
        return False

def plot_xvg(xvg_file, png_file, title, ylabel):
    """Parses XVG and plots it using matplotlib if available."""
    try:
        import matplotlib.pyplot as plt
        x, y = [], []
        with open(xvg_file, 'r') as f:
            for line in f:
                if not line.startswith(('@', '#')):
                    parts = line.split()
                    if len(parts) >= 2:
                        x.append(float(parts[0]))
                        y.append(float(parts[1]))
        
        if not x or not y:
            return False

        plt.figure(figsize=(8, 5))
        plt.plot(x, y, color='#1f77b4', linewidth=1.5)
        plt.title(title, fontweight='bold')
        plt.xlabel("Time (ps)", fontweight='bold')
        plt.ylabel(ylabel, fontweight='bold')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        plt.savefig(png_file, dpi=300)
        plt.close()
        return True
    except ImportError:
        # Silently fail if matplotlib isn't installed; user still gets the XVG
        return False
    except Exception as e:
        print(C_ERR + f"    [!] Plotting failed for {os.path.basename(xvg_file)}: {e}" + C_RESET)
        return False

def get_prefix(filename):
    return os.path.splitext(os.path.basename(filename))[0]

def extract_step_num(name):
    match = re.search(r'step(\d+\.\d+|\d+)', name)
    return float(match.group(1)) if match else 0.0

def main():
    print_header()

    raw_path = input(C_INFO + "Enter path to CHARMM-GUI extracted folder or its 'gromacs' subfolder: " + C_RESET)
    if not raw_path.strip():
        print(C_ERR + "No path provided. Exiting." + C_RESET)
        sys.exit(1)
    base_path = normalize_path(raw_path)

    if not os.path.exists(base_path):
        print(C_ERR + f"Path does not exist: {base_path}" + C_RESET)
        sys.exit(1)

    if os.path.isdir(base_path):
        if os.path.basename(base_path).lower() == "gromacs":
            gromacs_dir = base_path
        else:
            candidate = os.path.join(base_path, "gromacs")
            if os.path.isdir(candidate):
                gromacs_dir = candidate
            else:
                print(C_WARN + f"No 'gromacs' subfolder found inside {base_path}." + C_RESET)
                mdps = glob.glob(os.path.join(base_path, "*.mdp"))
                if mdps and os.path.exists(os.path.join(base_path, "topol.top")):
                    print(C_OK + "Found expected CHARMM-GUI files in the provided folder." + C_RESET)
                    gromacs_dir = base_path
                else:
                    print(C_ERR + "Could not locate 'gromacs' folder or expected files." + C_RESET)
                    sys.exit(1)
    else:
        print(C_ERR + f"Provided path is not a directory: {base_path}" + C_RESET)
        sys.exit(1)

    use_gpu = ask_yes_no_numeric("Do you want to use GPU acceleration for mdrun?", 
                                 "Use GPU only if your GROMACS was built with CUDA support.")
    use_mpi = ask_yes_no_numeric("Do you want to use MPI (gmx_mpi) for commands?", 
                                 "Use MPI only if your GROMACS was built with MPI support.")

    gmx_cmd = "gmx_mpi" if use_mpi else "gmx"
    if shutil_which(gmx_cmd) is None:
        print(C_WARN + f"Warning: '{gmx_cmd}' not found on PATH. Will attempt to run anyway." + C_RESET)

    # --- DYNAMIC FILE DISCOVERY ---
    init_files = glob.glob(os.path.join(gromacs_dir, "*_input.gro"))
    if not init_files:
        print(C_ERR + "Error: Could not find any *_input.gro file." + C_RESET)
        sys.exit(1)
    init_files.sort(key=lambda x: extract_step_num(os.path.basename(x)))
    init_base = get_prefix(init_files[-1]) 

    mini_files = glob.glob(os.path.join(gromacs_dir, "*_minimization.mdp"))
    if not mini_files:
        print(C_ERR + "Error: Could not find any *_minimization.mdp file." + C_RESET)
        sys.exit(1)
    mini_base = get_prefix(mini_files[0])

    equi_files = glob.glob(os.path.join(gromacs_dir, "*_equilibration.mdp"))
    if not equi_files:
        print(C_ERR + "Error: Could not find any *_equilibration.mdp file." + C_RESET)
        sys.exit(1)
    equi_files.sort(key=lambda x: extract_step_num(os.path.basename(x)))
    equi_bases = [get_prefix(x) for x in equi_files]

    prod_files = glob.glob(os.path.join(gromacs_dir, "*_production.mdp"))
    if not prod_files:
        print(C_ERR + "Error: Could not find any *_production.mdp file." + C_RESET)
        sys.exit(1)
    prod_base = get_prefix(prod_files[0])

    print(C_INFO + f"\n--- Detected System Architecture ---" + C_RESET)
    print(f"  Input File:      {init_base}.gro")
    print(f"  Minimization:    {mini_base}")
    print(f"  Equilibrations:  {len(equi_bases)} step(s)")
    for idx, e in enumerate(equi_bases, 1):
        print(f"    {idx}. {e}")
    print(f"  Production:      {prod_base}\n")

    # Intelligent Check: Parse README for maxwarn requirement (with -1 correction)
    maxwarn_args = []
    readme_files = [f for f in os.listdir(gromacs_dir) if "readme" in f.lower()]
    for rm in readme_files:
        try:
            with open(os.path.join(gromacs_dir, rm), 'r') as f:
                content = f.read()
                if "maxwarn" in content and mini_base in content:
                    match = re.search(r'-maxwarn\s+(-?\d+)', content)
                    if match:
                        warn_val = int(match.group(1))
                        warn_val = 1 if warn_val < 0 else warn_val
                        maxwarn_args = ["-maxwarn", str(warn_val)]
                    else:
                        maxwarn_args = ["-maxwarn", "1"]
                        
                    print(C_WARN + f"Note: Detected maxwarn requirement. Applying {maxwarn_args[0]} {maxwarn_args[1]} to Minimization." + C_RESET)
                    break
        except Exception:
            pass

    # --- BUILD COMMANDS ---
    steps = []
    prev_gro = f"{init_base}.gro"

    grompp_mini = [gmx_cmd, "grompp", "-f", f"{mini_base}.mdp", "-o", f"{mini_base}.tpr",
                   "-c", prev_gro, "-r", f"{init_base}.gro", "-p", "topol.top", "-n", "index.ndx"]
    if maxwarn_args:
        grompp_mini.extend(maxwarn_args)
    mdrun_mini = [gmx_cmd, "mdrun", "-v", "-deffnm", mini_base]
    steps.append((grompp_mini, mdrun_mini, "Minimization"))
    prev_gro = f"{mini_base}.gro"

    for eq_base in equi_bases:
        grompp_eq = [gmx_cmd, "grompp", "-f", f"{eq_base}.mdp", "-o", f"{eq_base}.tpr",
                     "-c", prev_gro, "-r", f"{init_base}.gro", "-p", "topol.top", "-n", "index.ndx"]
        mdrun_eq = [gmx_cmd, "mdrun", "-v", "-deffnm", eq_base]
        steps.append((grompp_eq, mdrun_eq, f"Equilibration ({eq_base})"))
        prev_gro = f"{eq_base}.gro"

    grompp_prod = [gmx_cmd, "grompp", "-f", f"{prod_base}.mdp", "-o", "md.tpr",
                   "-c", prev_gro, "-p", "topol.top", "-n", "index.ndx"]
    mdrun_prod = [gmx_cmd, "mdrun", "-v", "-deffnm", "md"]
    steps.append((grompp_prod, mdrun_prod, "Production"))

    if use_gpu:
        for i, (gpp, mdr, label) in enumerate(steps):
            if "-nb" not in mdr and "gpu" not in mdr:
                mdr_extended = mdr + ["-nb", "gpu"]
                steps[i] = (gpp, mdr_extended, label)

    total_commands = len(steps) * 2
    current_cmd = 0

    print()
    print(C_OK + f"Working directory: {gromacs_dir}" + C_RESET)
    print(C_OK + f"Will run {len(steps)} step groups ({total_commands} commands total)." + C_RESET)
    print(C_INFO + "Starting sequence. Press Ctrl+C to abort at any time." + C_RESET)

    try:
        for idx, (gpp_cmd, mdr_cmd, label) in enumerate(steps, start=1):
            
            # --- GROMPP ---
            current_cmd += 1
            print(C_INFO + "\n" + "="*60 + C_RESET)
            print(C_INFO + f"Step {idx}/{len(steps)}: {label} - grompp" + C_RESET)
            print(simple_progress_bar(current_cmd, total_commands))
            rc = run_command(gpp_cmd, cwd=gromacs_dir)
            if rc != 0:
                print(C_ERR + f"grompp failed with return code {rc}. Aborting." + C_RESET)
                sys.exit(rc)

            # --- MDRUN ---
            current_cmd += 1
            print(C_INFO + f"\nStep {idx}/{len(steps)}: {label} - mdrun" + C_RESET)
            print(simple_progress_bar(current_cmd, total_commands))
            rc = run_command(mdr_cmd, cwd=gromacs_dir)
            if rc != 0:
                print(C_ERR + f"mdrun failed with return code {rc}. Aborting." + C_RESET)
                sys.exit(rc)

            # --- POST-RUN AUDITING ---
            # Identify the output base name used by mdrun
            deffnm_idx = mdr_cmd.index("-deffnm")
            outbase = mdr_cmd[deffnm_idx + 1]
            edr_file = f"{outbase}.edr"

            if "Minimization" in label:
                print(C_INFO + f"\n[Auditing] Extracting Thermodynamics for {label}..." + C_RESET)
                xvg_name = f"{outbase}_potential.xvg"
                png_name = f"{outbase}_potential.png"
                if extract_energy(gmx_cmd, edr_file, xvg_name, "Potential", gromacs_dir):
                    print(C_OK + f"  -> Extracted {xvg_name}" + C_RESET)
                    if plot_xvg(os.path.join(gromacs_dir, xvg_name), os.path.join(gromacs_dir, png_name), "Minimization Potential Energy", "Potential Energy (kJ/mol)"):
                        print(C_OK + f"  -> Generated Plot: {png_name}" + C_RESET)

            elif "Equilibration" in label:
                print(C_INFO + f"\n[Auditing] Extracting Thermodynamics for {label}..." + C_RESET)
                terms = [("Temperature", "Temperature (K)"), ("Pressure", "Pressure (bar)"), ("Density", "Density (kg/m^3)")]
                for term, unit in terms:
                    xvg_name = f"{outbase}_{term.lower()}.xvg"
                    png_name = f"{outbase}_{term.lower()}.png"
                    if extract_energy(gmx_cmd, edr_file, xvg_name, term, gromacs_dir):
                        print(C_OK + f"  -> Extracted {xvg_name}" + C_RESET)
                        if plot_xvg(os.path.join(gromacs_dir, xvg_name), os.path.join(gromacs_dir, png_name), f"{outbase} {term}", unit):
                            print(C_OK + f"  -> Generated Plot: {png_name}" + C_RESET)

            time.sleep(0.5)

    except KeyboardInterrupt:
        print(C_WARN + "\nExecution interrupted by user (Ctrl+C). Exiting." + C_RESET)
        sys.exit(130)

    print(C_OK + "\nAll steps completed successfully." + C_RESET)
    print(C_INFO + "Check output files and graphs in your directory." + C_RESET)

if __name__ == "__main__":
    main()