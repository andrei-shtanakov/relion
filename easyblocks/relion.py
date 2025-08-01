##
# Custom EasyBlock for RELION installation
# Based on working bash script approach
##

import os
import tempfile
import shutil
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.filetools import copy_file, which, change_dir


class EB_RELION(CMakeMake):
    """
    Custom easyblock for RELION installation.
    Based on working bash script sequence.
    """

    @staticmethod
    def extra_options():
        """Extra easyconfig parameters specific to RELION easyblock."""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'conda_env_file': [None, "Path to conda environment_blackwell.yml file", CUSTOM],
            'python_env_name': ['relion-5.0', "Name of the conda environment", CUSTOM],
            'skip_conda_env': [False, "Skip conda environment creation", CUSTOM],
            'install_model_angelo': [False, "Install model-angelo after RELION", CUSTOM],
            'model_angelo_source': [None, "Path to model-angelo source archive", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize RELION easyblock."""
        super().__init__(*args, **kwargs)
        self.conda_env_path = None
        self.relion_src_dir = None

    def extract_step(self):
        """Extract sources and find correct directories."""
        self.log.info("=== RELION EXTRACT STEP START ===")
        super().extract_step()

        # Find the RELION source directory
        source_patterns = ['relion-5.0.0', 'relion-ver5.0', 'relion-5.0', 'relion-%s' % self.version]
        
        for pattern in source_patterns:
            candidate = os.path.join(self.builddir, pattern)
            if os.path.exists(candidate) and os.path.exists(os.path.join(candidate, 'environment_blackwell.yml')):
                self.relion_src_dir = candidate
                self.log.info(f"Found RELION source directory: {self.relion_src_dir}")
                break

        if not self.relion_src_dir:
            # Search for any directory with environment_blackwell.yml
            for item in os.listdir(self.builddir):
                path = os.path.join(self.builddir, item)
                if os.path.isdir(path) and os.path.exists(os.path.join(path, 'environment_blackwell.yml')):
                    self.relion_src_dir = path
                    self.log.info(f"Found RELION source directory (fallback): {self.relion_src_dir}")
                    break

        if not self.relion_src_dir:
            raise EasyBuildError("Could not find RELION source directory with environment_blackwell.yml")

        self.log.info("=== RELION EXTRACT STEP END ===")


    def _find_conda_cmd(self):
        """Find available conda command."""
        # Try which command first
        for cmd in ['conda', 'mamba', 'micromamba']:
            cmd_path = which(cmd)
            if cmd_path:
                self.log.info(f"Found {cmd} at: {cmd_path}")
                return cmd
        
        # Try EasyBuild modules
        conda_roots = ['Conda', 'anaconda2', 'miniconda2', 'anaconda3', 'miniconda3', 'miniforge3']
        for root_name in conda_roots:
            if get_software_root(root_name):
                return 'conda'

        return None

    def configure_step(self):
        """Configure RELION build."""
        self.log.info("=== RELION CONFIGURE STEP START ===")

        # Create torch directory early (like in bash script)
        torch_home = os.path.join(self.installdir, 'torch')
        os.makedirs(torch_home, exist_ok=True)
        self.log.info(f"Created torch directory: {torch_home}")

        # Setup conda environment OUTSIDE installdir to prevent deletion
        if not self.cfg['skip_conda_env']:
            self.log.info("Setting up conda environment...")
            # Создаем conda во временной директории, НЕ в installdir
            self.temp_conda_path = os.path.join(tempfile.gettempdir(), f'relion_conda_{os.getpid()}')
            self._setup_conda_environment_temp()
        else:
            self.log.info("Skipping conda environment setup")

        # Set up cmake options
        if hasattr(self, 'temp_conda_path') and os.path.exists(self.temp_conda_path):
            python_exe = os.path.join(self.temp_conda_path, 'bin', 'python')
            if os.path.exists(python_exe):
                self.cfg.update('configopts', f' -DPYTHON_EXE_PATH={python_exe}')
                self.log.info(f"Set Python exe path: {python_exe}")

        self.cfg.update('configopts', f' -DTORCH_HOME_PATH={torch_home}')

        # Override the build directory to be inside source (like in bash script)
        self.cfg['start_dir'] = self.relion_src_dir
        self.cfg['separate_build_dir'] = True
        self.cfg['build_in_installdir'] = False

        # Create build directory in source (НЕ устанавливаем cfg['builddir']!)
        build_dir = os.path.join(self.relion_src_dir, 'build')
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)

        self.log.info(f"Build directory: {build_dir}")
        self.log.info("=== RELION CONFIGURE STEP END ===")

        # Now call parent configure
        super().configure_step()

    def _setup_conda_environment_temp(self):
        """Create conda environment in TEMPORARY location (not in installdir)."""
        self.log.info("=== CONDA ENVIRONMENT SETUP START ===")

        # Find conda command
        conda_cmd = self._find_conda_cmd()
        if not conda_cmd:
            raise EasyBuildError("No conda available")

        self.log.info(f"Using conda command: {conda_cmd}")

        # Use TEMPORARY path instead of installdir
        self.log.info(f"Temporary conda environment path: {self.temp_conda_path}")

        # Remove existing environment if it exists
        if os.path.exists(self.temp_conda_path):
            self.log.info(f"Removing existing temporary conda environment: {self.temp_conda_path}")
            shutil.rmtree(self.temp_conda_path)

        # Find environment_blackwell.yml
        env_file = os.path.join(self.relion_src_dir, 'environment_blackwell.yml')
        if not os.path.exists(env_file):
            raise EasyBuildError(f"environment_blackwell.yml not found at: {env_file}")

        # Change to source directory for conda env creation
        orig_dir = os.getcwd()
        change_dir(self.relion_src_dir)

        try:
            # Create conda environment in temporary location
            cmd = f"{conda_cmd} env create --file environment_blackwell.yml --prefix {self.temp_conda_path}"
            self.log.info(f"Creating conda environment: {cmd}")
            run_shell_cmd(cmd)

            # Install additional packages via pip
            pip_cmd = os.path.join(self.temp_conda_path, 'bin', 'pip')
            if os.path.exists(pip_cmd):
                extra_packages = ['napari', 'napari-threedee', 'qtpy', 'psygnal', 'pyqt5']
                pip_install_cmd = f"{pip_cmd} install {' '.join(extra_packages)}"
                self.log.info(f"Installing extra packages: {pip_install_cmd}")
                run_shell_cmd(pip_install_cmd)
            else:
                self.log.warning(f"pip not found at: {pip_cmd}")

            # Clean conda cache
            cleanup_cmd = f"{conda_cmd} clean -ya"
            self.log.info(f"Running cleanup: {cleanup_cmd}")
            run_shell_cmd(cleanup_cmd)

        finally:
            change_dir(orig_dir)

        self.log.info("=== CONDA ENVIRONMENT SETUP END ===")

    def install_step(self):
        """Install RELION and then move conda environment to final location."""
        self.log.info("=== RELION INSTALL STEP START ===")

        super().install_step()

        if hasattr(self, 'temp_conda_path') and os.path.exists(self.temp_conda_path):
            final_conda_path = os.path.join(self.installdir, 'conda')
            self.log.info(f"Moving conda from {self.temp_conda_path} to {final_conda_path}")

            os.makedirs(self.installdir, exist_ok=True)

            shutil.move(self.temp_conda_path, final_conda_path)

            self.conda_env_path = final_conda_path
            self.log.info(f"Conda environment successfully moved to: {final_conda_path}")
        else:
            self.log.info("No temporary conda environment to move")

        # 3. Copy qsub.csh to bin
        qsub_src = os.path.join(self.relion_src_dir, 'gui', 'qsub.csh')
        qsub_dst = os.path.join(self.installdir, 'bin', 'qsub.csh')
        if os.path.exists(qsub_src):
            copy_file(qsub_src, qsub_dst)
            self.log.info(f"Copied qsub.csh to {qsub_dst}")

        # 4. Install model-angelo if requested
        if self.cfg.get('install_model_angelo') and self.cfg.get('model_angelo_source'):
            self._install_model_angelo()

        self.log.info("=== RELION INSTALL STEP END ===")

    def _install_model_angelo(self):
        """Install model-angelo following the bash script approach."""
        self.log.info("=== MODEL-ANGELO INSTALLATION START ===")
        
        model_angelo_src = self.cfg['model_angelo_source']
        if not os.path.exists(model_angelo_src):
            self.log.warning(f"Model-angelo source not found: {model_angelo_src}")
            return
        
        # Extract model-angelo
        extract_dir = tempfile.mkdtemp()
        try:
            run_shell_cmd(f"tar xzvf {model_angelo_src} -C {extract_dir}")
            
            # Find extracted directory
            model_angelo_dir = None
            for item in os.listdir(extract_dir):
                path = os.path.join(extract_dir, item)
                if os.path.isdir(path) and os.path.exists(os.path.join(path, 'install_script.sh')):
                    model_angelo_dir = path
                    break
            
            if not model_angelo_dir:
                self.log.warning("Could not find model-angelo directory with install_script.sh")
                return
            
            # Run installation script
            orig_dir = os.getcwd()
            change_dir(model_angelo_dir)
            
            # Activate conda environment and run install script
            activate_cmd = f"source {self.conda_env_path}/bin/activate"
            install_cmd = f"{activate_cmd} && source install_script.sh --download-weights"
            
            self.log.info(f"Installing model-angelo: {install_cmd}")
            run_shell_cmd(install_cmd, use_bash=True)
            
            change_dir(orig_dir)
            
        finally:
            # Cleanup
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
        
        self.log.info("=== MODEL-ANGELO INSTALLATION END ===")

    def make_module_extra(self):
        """Add conda environment to module."""
        txt = super().make_module_extra()

        if self.conda_env_path and os.path.exists(self.conda_env_path):
            txt += self.module_generator.set_environment('RELION_CONDA_ENV', self.conda_env_path)
            txt += self.module_generator.prepend_paths('PATH', os.path.join(self.conda_env_path, 'bin'))

        # Add torch home
        torch_home = os.path.join(self.installdir, 'torch')
        if os.path.exists(torch_home):
            txt += self.module_generator.set_environment('TORCH_HOME', torch_home)

        return txt

    def sanity_check_step(self):
        """Custom sanity check for RELION."""
        self.log.info("=== RELION SANITY CHECK START ===")
        
        paths = {
            'files': ['bin/relion', 'bin/relion_refine_mpi'],
            'dirs': ['bin'],
        }

        # Check for conda environment
        if not self.cfg['skip_conda_env']:
            conda_path = os.path.join(self.installdir, 'conda')
            if os.path.exists(conda_path):
                paths['dirs'].append('conda')

        # Check for torch directory
        torch_path = os.path.join(self.installdir, 'torch')
        if os.path.exists(torch_path):
            paths['dirs'].append('torch')

        commands = ['relion --version']

        super().sanity_check_step(custom_paths=paths, custom_commands=commands)
        self.log.info("=== RELION SANITY CHECK END ===")
