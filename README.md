# Project Dependency Installer

A powerful Python script that automates the process of downloading GitHub repositories and installing their dependencies across multiple package managers and programming languages.

## Features

### 1. Repository Management
- Clones GitHub repositories with retry logic and optimized settings
- Handles shallow cloning to minimize download size
- Supports subrepository detection and management

### 2. Multi-Language Support
Detects and installs dependencies for multiple programming languages and frameworks:

- Python (pip, pipenv)
- JavaScript/Node.js (npm, yarn, pnpm)
- Ruby (bundler)
- PHP (composer)
- Java (maven, gradle)
- Go
- Rust (cargo)
- .NET (nuget)
- Web3/Blockchain
  - Truffle
  - Hardhat
  - Solidity
  - Vyper

### 3. Environment Variable Management
- Automatically detects required environment variables from:
  - Source code files
  - .env files
  - Configuration files
- Supports various environment variable patterns across languages
- Securely prompts for missing environment variables
- Handles sensitive variables (passwords, keys, tokens) with masked input

### 4. Package Manager Version Control
- Detects required package manager versions from project files
- Automatically installs correct versions of package managers
- Handles Node.js version management through nvm
- Supports version constraints and compatibility requirements

### 5. Dependency Installation
- Recursive dependency detection and installation
- Handles multiple dependency file formats
- Implements retry logic for failed installations
- Cleans caches before installations
- Supports offline installations where possible

### 6. Cross-Platform Support
- Works on Windows, macOS, and Linux
- Adapts installation commands based on operating system
- Handles platform-specific package manager installations

## Usage

```python install_github_repo.py <github_repo_url>```

## Requirements

- Python 3.6+
- Git
- Internet connection for initial package manager installations

## Supported Dependency Files

The script recognizes and processes the following dependency files:

- `requirements.txt` (Python)
- `Pipfile` (Python/Pipenv)
- `package.json` (Node.js)
- `yarn.lock` (Yarn)
- `pnpm-lock.yaml` (pnpm)
- `Gemfile` (Ruby)
- `composer.json` (PHP)
- `pom.xml` (Java/Maven)
- `build.gradle` (Java/Gradle)
- `go.mod` (Go)
- `Cargo.toml` (Rust)
- `*.sln` (.NET)
- `truffle-config.js` (Truffle)
- `hardhat.config.js` (Hardhat)
- `solidity.json` (Solidity)
- `Vyperfile.yaml` (Vyper)

## Environment Variable Detection

The script scans for environment variables in:

- `.env` files
- Source code files
- Configuration files
- Comments in smart contracts

Supports various patterns including:
- Python: `os.getenv()`, `os.environ`
- JavaScript: `process.env`
- PHP: `getenv()`, `$_ENV`, `$_SERVER`
- Smart Contract comments

## Error Handling

- Implements retry logic for network-related operations
- Provides detailed logging of all operations
- Gracefully handles missing dependencies
- Reports installation failures with specific error messages

## Security Features

- Masks input for sensitive environment variables
- Supports secure package manager installations
- Validates repository URLs
- Implements safe dependency installation practices

## Limitations

- Requires appropriate system permissions for package manager installations
- Some package managers may need manual installation on certain systems
- Network connectivity required for initial setup
- May require additional system dependencies based on project requirements

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.
