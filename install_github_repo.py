import os
import subprocess
import sys
import shutil
from urllib.parse import urlparse
import time
import platform
import re
import getpass
import glob
from typing import List, Dict, Set
import logging
import json
import concurrent.futures
from functools import lru_cache
import argparse


def check_and_install_package_manager(manager: str, install_commands: List[List[str]]) -> None:
    """
    Check if a package manager is installed, and install it if not.

    Args:
        manager (str): The name of the package manager.
        install_commands (List[List[str]]): A list of commands to install the package manager.
    """
    logging.info(f"Checking if '{manager}' is installed...")
    if shutil.which(manager) is None:
        logging.info(f"'{manager}' not found. Initiating installation...")
        for cmd in install_commands:
            try:
                logging.info(f"Running command: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)
                logging.info(f"'{manager}' installed successfully using: {' '.join(cmd)}")
            except subprocess.CalledProcessError:
                logging.error(f"Failed to install '{manager}' using: {' '.join(cmd)}")
                sys.exit(1)
        logging.info(f"'{manager}' is now installed.")
    else:
        logging.info(f"'{manager}' is already installed.")


def detect_environment_variables(base_path: str) -> Set[str]:
    """
    Detect environment variables used in the project by scanning source files or using any .env* files.

    Args:
        base_path (str): The base directory path to search for environment variables.

    Returns:
        set: A set of environment variable names detected.
    """
    env_vars = set()
    # Define file extensions to scan, including Web3-specific files
    file_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.php', '.env', '.sol', '.vy']

    # Define regex patterns for different languages
    patterns = [
        # Python
        re.compile(r"os\.getenv\(['\"](\w+)['\"]\)"),
        re.compile(r"os\.environ\.get\(['\"](\w+)['\"]\)"),
        re.compile(r"os\.environ\[['\"](\w+)['\"]\]"),
        # JavaScript/TypeScript (including Web3 config files)
        re.compile(r"process\.env\.([A-Z_]+)"),
        # PHP
        re.compile(r"getenv\(['\"](\w+)['\"]\)"),
        re.compile(r"\$_ENV\[['\"](\w+)['\"]\]"),
        re.compile(r"\$_SERVER\[['\"](\w+)['\"]\]"),
        # Solidity (if using environment variables in comments or associated scripts)
        re.compile(r"//\s*Environment\s*Variable\s*:\s*(\w+)"),
        re.compile(r"//\s*ENV\s*VAR\s*:\s*(\w+)"),
        # Vyper (similar to Solidity)
        re.compile(r"#\s*Environment\s*Variable\s*:\s*(\w+)"),
        re.compile(r"#\s*ENV\s*VAR\s*:\s*(\w+)"),
    ]

    # List to hold paths of subrepositories
    subrepositories = []

    # Find all .env* files in the base_path
    env_files = glob.glob(os.path.join(base_path, ".env*"))
    env_files = [f for f in env_files if os.path.isfile(f)]

    if env_files:
        logging.info("Detected the following .env files: %s", ', '.join(os.path.basename(f) for f in env_files))
        for env_file in env_files:
            vars_from_file = parse_env_file(env_file)
            env_vars.update(vars_from_file.keys())
            # Set the variables in os.environ
            for var, value in vars_from_file.items():
                if var not in os.environ or os.environ[var] == '':
                    os.environ[var] = value
        # If .env files are present, skip source file scanning
        logging.info("Skipping environment variable detection from source files due to existing .env* files.")
    else:
        for root, dirs, files in os.walk(base_path):
            # Skip subrepositories
            if is_subrepository(root) and root != base_path:
                subrepositories.append(root)
                # Remove the subrepository directory from dirs to prevent os.walk from descending into it
                subrepo_dir = os.path.basename(root)
                if subrepo_dir in dirs:
                    dirs.remove(subrepo_dir)
                continue

            for file in files:
                if any(file.endswith(ext) for ext in file_extensions):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            for pattern in patterns:
                                matches = pattern.findall(content)
                                for match in matches:
                                    env_vars.add(match)
                    except (UnicodeDecodeError, FileNotFoundError):
                        # Skip files that can't be decoded or found
                        continue

        # Handle environment variables for subrepositories if needed
        for subrepo in subrepositories:
            logging.info("Detecting environment variables for subrepository: %s", subrepo)
            sub_env_vars = detect_environment_variables(subrepo)
            if sub_env_vars:
                logging.info("Detected environment variables in '%s': %s", subrepo, ', '.join(sub_env_vars))
                env_vars.update(sub_env_vars)
            else:
                logging.info("No environment variables detected in '%s'.", subrepo)

    return env_vars


def parse_env_file(env_file_path: str) -> Dict[str, str]:
    """
    Parse a .env* file to extract environment variable names and their values.

    Args:
        env_file_path (str): Path to the .env* file.

    Returns:
        dict: A dictionary of environment variable names and their corresponding values.
    """
    env_vars = {}
    try:
        with open(env_file_path, 'r', encoding='utf-8') as file:
            for line in file:
                # Ignore comments and empty lines
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    var, value = line.split('=', 1)
                    var = var.strip()
                    value = value.strip().strip('"').strip("'")  # Remove potential quotes
                    if var:
                        env_vars[var] = value
    except FileNotFoundError:
        logging.warning("Environment file '%s' not found.", env_file_path)
    except Exception as e:
        logging.error("Error reading environment file '%s': %s", env_file_path, e)
    return env_vars


def prompt_for_env_vars(env_vars: Set[str]) -> None:
    """
    Prompt the user to input values for missing environment variables and set them.

    Args:
        env_vars (set): A set of environment variable names to check and prompt.
    """
    missing_vars = {var for var in env_vars if var not in os.environ or os.environ[var] == ''}

    if not missing_vars:
        logging.info("All detected environment variables are already set.")
        return

    logging.info("Missing Environment Variables Detected:")
    for var in missing_vars:
        # For sensitive variables, use getpass to hide input
        if any(keyword in var.upper() for keyword in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN']):
            value = getpass.getpass(f"Please enter the value for environment variable '{var}': ")
        else:
            value = input(f"Please enter the value for environment variable '{var}': ")
        os.environ[var] = value
        logging.info("Environment variable '%s' set.", var)

    # Update the .env* file
    update_env_files(missing_vars)


def update_env_files(missing_vars: Set[str]) -> None:
    """
    Update existing .env* files with the provided environment variables.
    If no .env* files exist, create a new .env file.
    """
    # Find all .env* files in the current directory
    env_files = glob.glob(".env*")
    env_files = [f for f in env_files if os.path.isfile(f)]

    if not env_files:
        target_env_file = ".env"
        logging.info("No .env* files found. Creating '%s'.", target_env_file)
        with open(target_env_file, 'w') as f:
            for var in missing_vars:
                f.write(f"{var}={os.environ[var]}\n")
        logging.info("Created '%s' with the provided environment variables.", target_env_file)
    else:
        # Update the first .env* file found
        target_env_file = env_files[0]
        logging.info("Updating '%s' with the provided environment variables.", target_env_file)
        
        # Read existing variables
        existing_vars = {}
        if os.path.exists(target_env_file):
            with open(target_env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            existing_vars[key.strip()] = value.strip()

        # Update with new variables
        for var in missing_vars:
            existing_vars[var] = os.environ[var]

        # Write back all variables
        with open(target_env_file, 'w') as f:
            for var, value in existing_vars.items():
                f.write(f"{var}={value}\n")
        
        logging.info("Updated '%s' successfully.", target_env_file)


def is_subrepository(path: str) -> bool:
    """
    Check if a given path is a Git subrepository by looking for a .git folder or file.

    Args:
        path (str): The directory path to check.

    Returns:
        bool: True if the path is a subrepository, False otherwise.
    """
    git_path = os.path.join(path, '.git')
    if os.path.isdir(git_path):
        return True
    elif os.path.isfile(git_path):
        try:
            with open(git_path, 'r') as f:
                content = f.read()
                return 'gitdir' in content
        except Exception:
            return False
    return False


def download_and_install(repo_url: str) -> None:
    """
    Downloads a GitHub repository and installs its dependencies.

    Args:
        repo_url (str): The URL of the GitHub repository.
    """
    # Parse repository name from URL
    parsed_url = urlparse(repo_url)
    repo_name = os.path.splitext(os.path.basename(parsed_url.path))[0]

    if os.path.exists(repo_name):
        logging.info("Directory '%s' already exists. Skipping clone.", repo_name)
    else:
        # Attempt to clone with retries
        run_git_clone(repo_url)

    os.chdir(repo_name)

    # Define install commands for package managers with OS-specific commands
    package_managers_install_commands: Dict[str, Dict[str, List[List[str]]]] = {
        'pipenv': {
            'Darwin': [['pip', 'install', 'pipenv']],
            'Linux': [['pip', 'install', 'pipenv']],
            'Windows': [['pip', 'install', 'pipenv']],
        },
        'yarn': {
            'Darwin': [['npm', 'install', '-g', 'yarn']],
            'Linux': [['npm', 'install', '-g', 'yarn']],
            'Windows': [['npm', 'install', '-g', 'yarn']],
        },
        'npm': {
            'Darwin': [['npm', 'install', '-g', 'npm']],
            'Linux': [['npm', 'install', '-g', 'npm']],
            'Windows': [['npm', 'install', '-g', 'npm']],
        },
        'bundle': {
            'Darwin': [['gem', 'install', 'bundler']],
            'Linux': [['gem', 'install', 'bundler']],
            'Windows': [['gem', 'install', 'bundler']],
        },
        'composer': {
            'Darwin': [
                ['curl', '-sS', 'https://getcomposer.org/installer', '-o', 'composer-setup.php'],
                ['php', 'composer-setup.php'],
                ['mv', 'composer.phar', '/usr/local/bin/composer'],
                ['php', '-r', "unlink('composer-setup.php');"],
            ],
            'Linux': [
                ['curl', '-sS', 'https://getcomposer.org/installer', '-o', 'composer-setup.php'],
                ['php', 'composer-setup.php'],
                ['mv', 'composer.phar', '/usr/local/bin/composer'],
                ['php', '-r', "unlink('composer-setup.php');"],
            ],
            'Windows': [
                ['php', 'composer-setup.php'],
                ['move', 'composer.phar', 'C:\\Composer\\composer.phar'],
                ['php', '-r', "unlink('composer-setup.php');"],
            ],
        },
        'mvn': {
            'Darwin': [['brew', 'install', 'maven']],
            'Linux': [['sudo', 'apt-get', 'install', '-y', 'maven']],
            'Windows': [['choco', 'install', 'maven', '-y']],
        },
        'gradle': {
            'Darwin': [['brew', 'install', 'gradle']],
            'Linux': [['sudo', 'apt-get', 'install', '-y', 'gradle']],
            'Windows': [['choco', 'install', 'gradle', '-y']],
        },
        'go': {
            'Darwin': [['brew', 'install', 'go']],
            'Linux': [['sudo', 'apt-get', 'install', '-y', 'golang']],
            'Windows': [['choco', 'install', 'go', '-y']],
        },
        'truffle': {
            'Darwin': [['npm', 'install', '-g', 'truffle']],
            'Linux': [['npm', 'install', '-g', 'truffle']],
            'Windows': [['npm', 'install', '-g', 'truffle']],
        },
        'hardhat': {
            'Darwin': [['npm', 'install', '--save-dev', 'hardhat']],
            'Linux': [['npm', 'install', '--save-dev', 'hardhat']],
            'Windows': [['npm', 'install', '--save-dev', 'hardhat']],
        },
        'solc': {
            'Darwin': [['brew', 'install', 'solidity']],
            'Linux': [['sudo', 'apt-get', 'install', '-y', 'solc']],
            'Windows': [['choco', 'install', 'solidity', '-y']],
        },
        'vyper': {
            'Darwin': [['pip', 'install', 'vyper']],
            'Linux': [['pip', 'install', 'vyper']],
            'Windows': [['pip', 'install', 'vyper']],
        },
        'pnpm': {
            'Darwin': [['npm', 'install', '-g', 'pnpm']],
            'Linux': [['npm', 'install', '-g', 'pnpm']],
            'Windows': [['npm', 'install', '-g', 'pnpm']],
        },
        'nuget': {
            'Darwin': [['brew', 'install', 'nuget']],
            'Linux': [['sudo', 'apt-get', 'install', '-y', 'nuget']],
            'Windows': [['choco', 'install', 'nuget.commandline', '-y']],
        },
        'pip': {
            'Darwin': [['brew', 'install', 'python']],
            'Linux': [['sudo', 'apt-get', 'install', '-y', 'python3']],
            'Windows': [['choco', 'install', 'python', '-y']],
        },
        'cargo': {
            'Darwin': [['curl', '--proto', '=https', '--tlsv1.2', '-sSf', 'https://sh.rustup.rs', '|', 'sh', '-s', '--', '-y']],
            'Linux': [['curl', '--proto', '=https', '--tlsv1.2', '-sSf', 'https://sh.rustup.rs', '|', 'sh', '-s', '--', '-y']],
            'Windows': [['curl', '--proto', '=https', '--tlsv1.2', '-sSf', 'https://win.rustup.rs', '-o', 'rustup-init.exe'],
                       ['rustup-init.exe', '-y']],
        },
        # Add other package managers and their install commands as needed
    }

    # Define dependency files and corresponding package managers
    dependency_files = {
        'requirements.txt': 'pip',
        'Pipfile': 'pipenv',
        'package.json': 'npm',
        'yarn.lock': 'yarn',
        'Gemfile': 'bundle',
        'composer.json': 'composer',
        'pom.xml': 'mvn',
        'build.gradle': 'gradle',
        'go.mod': 'go',
        'truffle-config.js': 'truffle',
        'hardhat.config.js': 'hardhat',
        'Vyperfile.yaml': 'vyper',
        'solidity.json': 'solc',
        'Pipfile.lock': 'pipenv',
        'pnpm-lock.yaml': 'pnpm',
        '*.sln': 'nuget',
        'requirements-dev.txt': 'pip',
        'Cargo.toml': 'cargo',
        'rust-toolchain.toml': 'cargo',
        'rust-toolchain': 'cargo',
    }

    # Define commands to install dependencies based on dependency files
    dependency_install_commands = {
        'requirements.txt': ['pip', 'install', '--no-cache-dir', '--ignore-installed', '--no-deps', '-r', 'requirements.txt'],
        'requirements-dev.txt': ['pip', 'install', '--no-cache-dir', '--ignore-installed', '--no-deps', '-r', 'requirements-dev.txt'],
        'Pipfile': ['pipenv', 'install', '--skip-lock'],
        'package.json': ['npm', 'install', '--no-optional'],
        'yarn.lock': ['yarn', 'install', '--frozen-lockfile'],
        'Gemfile': ['bundle', 'install', '--without', 'development', 'test'],
        'composer.json': ['composer', 'install', '--no-dev', '--no-suggest'],
        'pom.xml': ['mvn', 'install', '-DskipTests', '-Dmaven.test.skip=true'],
        'build.gradle': ['gradle', 'build', '-x', 'test'],
        'go.mod': ['go', 'mod', 'download', '-x'],
        'pnpm-lock.yaml': ['pnpm', 'install', '--prod', '--no-optional'],
        '*.sln': ['nuget', 'restore', '-NonInteractive'],
        'truffle-config.js': ['truffle', 'compile', '--quiet'],
        'hardhat.config.js': ['hardhat', 'compile', '--no-typechain'],
        'Vyperfile.yaml': ['vyper', '--version'],
        'solidity.json': ['solc', '--install', 'all'],
        'Cargo.toml': ['cargo', 'build', '--no-default-features'],
        'rust-toolchain.toml': ['rustup', 'show'],
        'rust-toolchain': ['rustup', 'show'],
    }

    # Detect the current operating system
    current_os = platform.system()
    os_key = current_os if current_os in ['Darwin', 'Linux', 'Windows'] else None
    if not os_key:
        logging.error("Unsupported operating system: %s. Exiting.", current_os)
        sys.exit(1)

    # Update the install commands to use the appropriate commands based on the OS
    for manager, commands_by_os in list(package_managers_install_commands.items()):
        if os_key in commands_by_os:
            package_managers_install_commands[manager] = commands_by_os[os_key]
        else:
            logging.warning("No install commands defined for package manager '%s' on OS '%s'. Skipping.", manager, os_key)
            del package_managers_install_commands[manager]

    # Identify which package managers are required based on dependency files
    required_managers = set()
    for file, manager in dependency_files.items():
        if file.startswith('*'):
            # Handle wildcard dependency files
            pattern = file.lstrip('*')
            for f in os.listdir('.'):
                if f.endswith(pattern):
                    required_managers.add(manager)
        elif os.path.isfile(file):
            required_managers.add(manager)

    if not required_managers:
        logging.info("No recognized dependency files found. No dependencies to install.")
    else:
        # Install only the required package managers in parallel
        install_packages_parallel(required_managers, package_managers_install_commands)

    # Detect and handle environment variables
    logging.info("Detecting required environment variables...")
    env_vars = detect_environment_variables('.')
    if env_vars:
        prompt_for_env_vars(env_vars)
    else:
        logging.info("No environment variables detected.")

    # After installing all required package managers and handling environment variables, install dependencies once
    find_and_install_dependencies('.', dependency_files, dependency_install_commands)

    logging.info("Setup complete.")


def run_git_clone(repo_url: str, retries: int = 3, delay: int = 5) -> None:
    """
    Clone a Git repository with retry logic.

    Args:
        repo_url (str): The URL of the Git repository to clone.
        retries (int, optional): Number of retry attempts. Defaults to 3.
        delay (int, optional): Delay between retries in seconds. Defaults to 5.

    Raises:
        subprocess.CalledProcessError: If all retry attempts fail.
    """
    logging.info(f"Starting to clone repository: {repo_url}")
    for attempt in range(1, retries + 1):
        try:
            logging.info(f"Attempt {attempt} to clone the repository...")
            subprocess.run(
                ['git', 'config', '--global', 'http.postBuffer', '1048576000'],
                check=True
            )
            subprocess.run(
                ['git', 'clone', '--depth', '1', '--config', 'core.compression=0', '--verbose', repo_url],
                check=True
            )
            logging.info("Repository cloned successfully.")
            return
        except subprocess.CalledProcessError as e:
            logging.warning(f"Attempt {attempt} failed: {e}")
            if attempt < retries:
                logging.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logging.error("All retry attempts to clone the repository have failed.")
                raise


def get_required_package_manager_version(base_path: str) -> Dict[str, str]:
    """
    Detect required package manager versions from project files.
    Returns a dict with package manager names and their required versions.
    """
    versions = {}
    
    # Check for package.json first since it's the most authoritative source
    package_json = os.path.join(base_path, 'package.json')
    if os.path.exists(package_json):
        try:
            with open(package_json) as f:
                data = json.load(f)
                engines = data.get('engines', {})
                
                # Get Node.js version requirement
                if 'node' in engines:
                    versions['node'] = engines['node']
                else:
                    # If no Node version specified, check dependencies for hints
                    deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                    if 'ganache-core' in deps or 'truffle' in deps:
                        versions['node'] = '<=16.0.0'  # These packages typically need Node 16 or lower
                
                # Get package manager versions if specified
                if 'yarn' in engines:
                    versions['yarn'] = engines['yarn']
                if 'npm' in engines:
                    versions['npm'] = engines['npm']
                elif not versions.get('npm'):
                    # If no npm version specified but using older packages, set compatible version
                    if versions.get('node', '').startswith('<=16'):
                        versions['npm'] = '<=6.14.0'

        except (json.JSONDecodeError, IOError):
            logging.warning("Could not parse package.json, using fallback versions")
            # Fallback to safe versions
            versions['node'] = '<=16.0.0'
            versions['npm'] = '<=6.14.0'
    
    # Only check lock files if we don't have versions from package.json
    if 'yarn' not in versions and os.path.exists(os.path.join(base_path, 'yarn.lock')):
        try:
            with open(os.path.join(base_path, 'yarn.lock')) as f:
                content = f.read()
                match = re.search(r'# yarn lockfile v(\d+)', content)
                if match:
                    lockfile_version = int(match.group(1))
                    if lockfile_version == 1:
                        versions['yarn'] = '1.x'  # Classic Yarn
                    else:
                        versions['yarn'] = '>=2.0.0'  # Modern Yarn
        except IOError:
            pass
    
    if 'npm' not in versions and os.path.exists(os.path.join(base_path, 'package-lock.json')):
        try:
            with open(os.path.join(base_path, 'package-lock.json')) as f:
                data = json.load(f)
                lockfile_version = data.get('lockfileVersion', 1)
                # Map lockfile version to compatible npm version
                lockfile_to_npm = {
                    1: "<=6.14.0",  # Old format, compatible with Node <= 16
                    2: ">=7.0.0",   # Modern format
                    3: ">=7.0.0"    # Modern format with better monorepo support
                }
                versions['npm'] = lockfile_to_npm.get(lockfile_version, ">=7.0.0")
        except (json.JSONDecodeError, IOError):
            pass
    
    return versions


def install_required_package_manager_version(manager: str, version: str) -> None:
    """
    Install the required version of a package manager.
    """
    try:
        if manager == 'node':
            # Check if nvm is installed
            if not shutil.which('nvm'):
                logging.info("nvm not found. Installing...")
                current_os = platform.system()
                
                if current_os == 'Linux' or current_os == 'Darwin':
                    # Install nvm on Linux/macOS
                    try:
                        # Download and run the nvm installation script
                        subprocess.run(
                            'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash',
                            shell=True,
                            check=True
                        )
                        
                        # Source nvm in the current session
                        nvm_dir = os.path.expanduser('~/.nvm')
                        os.environ['NVM_DIR'] = nvm_dir
                        
                        # Create and execute a shell script that sources nvm and installs Node
                        with open('temp_nvm.sh', 'w') as f:
                            f.write(f'''#!/bin/bash
                            export NVM_DIR="{nvm_dir}"
                            [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"  # This loads nvm
                            [ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"
                            nvm install {version.replace('>=', '')}
                            nvm use {version.replace('>=', '')}
                            ''')
                        
                        # Make the script executable and run it
                        os.chmod('temp_nvm.sh', 0o755)
                        subprocess.run(['/bin/bash', './temp_nvm.sh'], check=True)
                        
                        # Clean up
                        os.remove('temp_nvm.sh')
                        
                        logging.info("nvm and Node.js installed successfully")
                        return  # Exit the function here since Node is already installed
                    except subprocess.CalledProcessError as e:
                        logging.error(f"Failed to install nvm: {e}")
                        raise
                
                elif current_os == 'Windows':
                    # Install nvm-windows
                    try:
                        # Download nvm-windows installer
                        subprocess.run(
                            'curl -o nvm-setup.exe https://github.com/coreybutler/nvm-windows/releases/latest/download/nvm-setup.exe',
                            shell=True,
                            check=True
                        )
                        
                        # Run the installer silently
                        subprocess.run('nvm-setup.exe /SILENT /NORESTART', shell=True, check=True)
                        
                        # Clean up the installer
                        os.remove('nvm-setup.exe')
                        
                        # Refresh environment variables
                        os.environ['NVM_HOME'] = os.path.expandvars('%PROGRAMFILES%\\nvm')
                        os.environ['NVM_SYMLINK'] = os.path.expandvars('%PROGRAMFILES%\\nodejs')
                        
                        logging.info("nvm-windows installed successfully")
                    except subprocess.CalledProcessError as e:
                        logging.error(f"Failed to install nvm-windows: {e}")
                        raise
                
                else:
                    logging.error(f"Unsupported operating system: {current_os}")
                    raise Exception(f"Unsupported operating system: {current_os}")

            # Extract major version if using >=X.X.X format
            version_num = version.replace('>=', '').split('.')[0]
            subprocess.run(f'nvm install {version_num} && nvm use {version_num}', 
                         shell=True, check=True)
            logging.info(f"Switched to node version {version_num}")
            
        elif manager == 'yarn':
            if version.startswith('^') or version.startswith('~'):
                version = version[1:]
            subprocess.run(['npm', 'install', '-g', f'yarn@{version}'], check=True)
            logging.info(f"Installed yarn version {version}")
        elif manager == 'npm':
            if version.startswith('^') or version.startswith('~'):
                version = version[1:]
            subprocess.run(['npm', 'install', '-g', f'npm@{version}'], check=True)
            logging.info(f"Installed npm version {version}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to install {manager} version {version}: {e}")
        raise


def find_and_install_dependencies(
    base_path: str,
    dependency_files: Dict[str, str],
    dependency_install_commands: Dict[str, str]
) -> None:
    """
    Recursively find and install dependencies based on dependency files.

    Args:
        base_path (str): The base directory path to search for dependencies.
        dependency_files (dict): Mapping of dependency files to their package managers.
        dependency_install_commands (dict): Mapping of dependency files to their install commands.
    """
    # Check for required package manager versions first
    required_versions = get_required_package_manager_version(base_path)
    
    # Install required versions if found
    for manager, version in required_versions.items():
        if version:
            logging.info(f"Required {manager} version: {version}")
            install_required_package_manager_version(manager, version)

    # Define a list of folders to exclude from dependency checks
    excluded_folders = [
        'node_modules', 'venv', '__pycache__', 'build', 'dist',
        '.terraform', 'env', 'target'
    ]

    for root, dirs, files in os.walk(base_path):
        # Remove excluded directories from dirs list to prevent recursion
        dirs[:] = [d for d in dirs if d not in excluded_folders and not d.startswith('.')]
        
        # Skip processing if we're in an excluded folder
        if any(excluded in root.split(os.sep) for excluded in excluded_folders):
            continue

        # Handle Node.js dependencies
        if any(f in files for f in ['package.json', 'yarn.lock', 'package-lock.json']):
            try:
                subprocess.run(['npm', 'install', '--legacy-peer-deps'], check=True, cwd=root)
                logging.info(f"Node.js dependencies installed successfully in '{root}'")
            except subprocess.CalledProcessError as e:
                logging.error(f"Failed to install Node.js dependencies in '{root}': {e}")

        for file in files:
            if file in ['package.json', 'yarn.lock', 'package-lock.json', 'pnpm-lock.yaml']:
                continue
                
            for dep_file_pattern, manager in dependency_files.items():
                if isinstance(dep_file_pattern, str) and dep_file_pattern.startswith('*'):
                    pattern = dep_file_pattern.lstrip('*')
                    if file.endswith(pattern):
                        try:
                            max_retries = 3
                            retry_delay = 5

                            for attempt in range(max_retries):
                                try:
                                    if 'pip' in dependency_install_commands[dep_file_pattern]:
                                        logging.info(f"Installing dependencies for packages in {file}")
                                        
                                        # Simplified pip install command with no cache
                                        pip_commands = [
                                            ['pip', 'install', '--no-cache-dir', '-r', file],
                                            ['python', '-m', 'pip', 'install', '--no-cache-dir', '-r', file],
                                            ['pip3', 'install', '--no-cache-dir', '-r', file]
                                        ]

                                        success = False
                                        for cmd in pip_commands:
                                            try:
                                                subprocess.run(cmd, check=True, cwd=root)
                                                success = True
                                                logging.info(f"Dependencies from {file} installed successfully in '{root}'")
                                                break
                                            except subprocess.CalledProcessError:
                                                continue

                                        if not success:
                                            raise Exception("All pip installation attempts failed")

                                    break

                                except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                                    if attempt == max_retries - 1:
                                        logging.error(f"Failed to install dependencies using {file} in '{root}': {e}")
                                        raise
                                    logging.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
                                    time.sleep(retry_delay)
                                    retry_delay *= 2
                        except subprocess.CalledProcessError as e:
                            logging.error(f"Failed to install dependencies using {file} in '{root}': {e}")
                elif file == dep_file_pattern:
                    try:
                        max_retries = 3
                        retry_delay = 5

                        for attempt in range(max_retries):
                            try:
                                cmd = dependency_install_commands[dep_file_pattern]
                                subprocess.run(cmd, check=True, cwd=root, timeout=300)
                                logging.info(f"Dependencies from {file} installed successfully in '{root}'")
                                break

                            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                                if attempt == max_retries - 1:
                                    logging.error(f"Failed to install dependencies using {file} in '{root}': {e}")
                                    raise
                                logging.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
                                time.sleep(retry_delay)
                                retry_delay *= 2
                    except subprocess.CalledProcessError as e:
                        logging.error(f"Failed to install dependencies using {file} in '{root}': {e}")


def install_packages_parallel(required_managers, package_managers_install_commands):
    """
    Install the required package managers in parallel.

    Args:
        required_managers (set): A set of required package managers.
        package_managers_install_commands (dict): Installation commands for package managers.
    """
    logging.info("Starting parallel installation of required package managers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for manager in required_managers:
            if manager in package_managers_install_commands:
                commands = package_managers_install_commands[manager]
                futures.append(
                    executor.submit(check_and_install_package_manager, manager, commands)
                )
        concurrent.futures.wait(futures)
    logging.info("All required package managers have been installed.")


@lru_cache(maxsize=None)
def get_package_manager_version(manager: str) -> str:
    """Cache package manager version checks."""
    try:
        result = subprocess.run([manager, '--version'], 
                              capture_output=True, 
                              text=True, 
                              check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def parse_arguments():
    parser = argparse.ArgumentParser(description="Download and install GitHub repository dependencies.")
    parser.add_argument('repo_url', type=str, help='URL of the GitHub repository to clone and install.')
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help='Set the logging level (default: INFO).')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    if not args.repo_url:
        logging.error("Usage: python download_and_install.py <github_repo_url>")
        sys.exit(1)

    repo_url = args.repo_url
    try:
        download_and_install(repo_url)
    except Exception as e:
        logging.error("An error occurred: %s", e)
        sys.exit(1)