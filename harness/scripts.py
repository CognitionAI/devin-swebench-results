import re
from dataclasses import dataclass

from .constants import (
    MAP_REPO_TO_INSTALL,
    MAP_REPO_TO_TEST_FRAMEWORK,
    MAP_VERSION_TO_INSTALL,
)
from .utils import (
    get_test_directives,
    get_requirements,
    get_environment_yml,
)
from .types import SwebenchInstance


SWEBENCH_PROMPT = """
Please help me resolve this issue in the repository {repo_name}. I've checked out the repository in your local machine at ~/{repo_directory} and set up a conda env for you (use `conda activate {env_name}`).

ISSUE:
{problem_statement}
""".strip()

HEREDOC_DELIMITER = "EOF_59812759871"

DIFF_MODIFIED_FILE_REGEX = r"--- a/(.*)"


@dataclass
class TestSpec:
    instance_id: str
    setup_script: str
    prompt: str
    eval_script: str


def make_test_spec(instance: SwebenchInstance) -> TestSpec:
    instance_id = instance["instance_id"]
    repo = instance["repo"]
    version = instance["version"]
    base_commit = instance["base_commit"]
    problem_statement = instance["problem_statement"]
    hints_text = instance["hints_text"]
    test_patch = instance["test_patch"]

    repo_directory = repo.split("/")[-1]
    env_name = repo_directory

    setup_commands = [
        # Setup miniconda and activate it
        "wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_23.11.0-2-Linux-x86_64.sh' -O miniconda.sh",
        "bash miniconda.sh -b -p $HOME/miniconda3",
        "source $HOME/miniconda3/bin/activate && conda init --all",
        f"git clone -o origin --no-tags https://github.com/{instance['repo']} {repo_directory}",
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        # Remove the remote so Devin won't see newer commits.
        f"git remote remove origin",
    ]
    if repo in MAP_REPO_TO_INSTALL:
        setup_commands.append(MAP_REPO_TO_INSTALL[repo])

    install = MAP_VERSION_TO_INSTALL[repo][version]

    # Create conda environment according to install instructinos
    pkgs = install.get("packages", "")
    if pkgs == "requirements.txt":
        # Create environment
        cmd = f"conda create -n {env_name} python={install['python']} -y"
        setup_commands.append(cmd)

        # Install dependencies
        reqs = get_requirements(instance)
        path_to_reqs = "$HOME/requirements.txt"
        setup_commands.append(
            f"cat <<'{HEREDOC_DELIMITER}' > {path_to_reqs}\n{reqs}\n{HEREDOC_DELIMITER}"
        )
        cmd = f"conda activate {env_name} && pip install -r {path_to_reqs}"
        setup_commands.append(cmd)

        setup_commands.append(f"rm {path_to_reqs}")
    elif pkgs == "environment.yml":
        # Create environment from yml
        reqs = get_environment_yml(instance, env_name)
        path_to_reqs = "$HOME/environment.yml"
        setup_commands.append(
            f"cat <<'{HEREDOC_DELIMITER}' > {path_to_reqs}\n{reqs}\n{HEREDOC_DELIMITER}"
        )
        if "no_use_env" in install and install["no_use_env"]:
            # `conda create` based installation
            cmd = f"conda create -c conda-forge -n {env_name} python={install['python']} -y"
            setup_commands.append(cmd)

            # Install dependencies
            cmd = f"conda env update -f {path_to_reqs}"
            setup_commands.append(cmd)
        else:
            # `conda env create` based installation
            cmd = f"conda env create --file {path_to_reqs}"
            setup_commands.append(cmd)

        # Remove environment.yml
        setup_commands.append(f"rm {path_to_reqs}")
    else:
        # Create environment + install dependencies
        cmd = f"conda create -n {env_name} python={install['python']} {pkgs} -y"
        setup_commands.append(cmd)

    setup_commands.append(f"conda activate {env_name}")

    # Install additional packages if specified
    if "pip_packages" in install:
        cmd = f"pip install {install['pip_packages']}"
        setup_commands.append(cmd)

    # Run pre-install set up if provided
    if "pre_install" in install:
        for pre_install in install["pre_install"]:
            setup_commands.append(pre_install)

    if "install" in install:
        setup_commands.append(install["install"])

    # Reset test files to the state they should be in before the patch.
    test_files = re.findall(DIFF_MODIFIED_FILE_REGEX, test_patch)
    reset_tests_command = f"git checkout {base_commit} {' '.join(test_files)}"
    apply_test_patch_command = (
        f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{test_patch}\n{HEREDOC_DELIMITER}"
    )

    test_command = " ".join(
        [MAP_REPO_TO_TEST_FRAMEWORK[instance["repo"]], *get_test_directives(instance)]
    )

    eval_commands = [
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        f"git status",
        f"git show",
        f"git diff {base_commit}",
        f"conda activate {env_name}",
        reset_tests_command,
        apply_test_patch_command,
        test_command,
    ]

    setup_script = "\n".join(["set -euxo pipefail"] + setup_commands) + "\n"
    eval_script = "\n".join(["set -euxo pipefail"] + eval_commands) + "\n"

    return TestSpec(
        instance_id=instance_id,
        setup_script=setup_script,
        prompt=SWEBENCH_PROMPT.format(
            repo_name=repo,
            problem_statement=problem_statement,
            repo_directory=repo_directory,
            env_name=env_name,
        ),
        eval_script=eval_script,
    )
