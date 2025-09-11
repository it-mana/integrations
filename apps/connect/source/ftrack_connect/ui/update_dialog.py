# :coding: utf-8
# :copyright: Copyright (c) 2014-2023 ftrack

import logging
import os
import platform
import subprocess
import tempfile
import webbrowser

import ftrack_connect.ui.theme
import requests

logger = logging.getLogger(__name__)


class DownloadProgressDialog:
    '''Dialog to show download progress during automatic update.'''

    def __init__(self, parent=None):
        '''Initialize download progress dialog.'''
        self.parent = parent
        self.dialog = None
        self.progress_bar = None
        self.label = None
        self.cancelled = False

    def create_dialog(self):
        '''Create and configure the download progress dialog.'''
        try:
            from PySide6 import QtCore, QtWidgets
        except ImportError:
            from PySide2 import QtCore, QtWidgets

        # Create dialog
        self.dialog = QtWidgets.QDialog(self.parent)
        self.dialog.setWindowTitle('Downloading Update')
        self.dialog.setFixedSize(400, 150)
        self.dialog.setModal(True)

        # Layout
        layout = QtWidgets.QVBoxLayout(self.dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Status label
        self.label = QtWidgets.QLabel('Preparing download...')
        layout.addWidget(self.label)

        # Progress bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Cancel button
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        cancel_button = QtWidgets.QPushButton('Cancel')
        cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

        return self.dialog

    def _on_cancel(self):
        '''Handle cancel button click.'''
        self.cancelled = True
        self.dialog.reject()

    def update_progress(self, progress, status_text):
        '''Update progress bar and status text.'''
        if self.progress_bar:
            self.progress_bar.setValue(int(progress))
        if self.label:
            self.label.setText(status_text)

    def show(self):
        '''Show the progress dialog.'''
        if not self.dialog:
            self.create_dialog()
        self.dialog.show()

    def close(self):
        '''Close the progress dialog.'''
        if self.dialog:
            self.dialog.close()


def download_file_with_progress(url, destination, progress_callback=None):
    '''Download a file with progress tracking.

    Args:
        url (str): URL to download from
        destination (str): Local file path to save to
        progress_callback (callable): Function to call with progress updates

    Returns:
        bool: True if download successful, False otherwise
    '''
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback and total_size > 0:
                        progress = (downloaded / total_size) * 100
                        progress_callback(
                            progress,
                            f'Downloaded {downloaded // 1024} KB of {total_size // 1024} KB',
                        )

        return True

    except Exception as e:
        logger.error(f'Error downloading file: {e}')
        return False


class UpdateDialog:
    '''Dialog to show update notifications and allow user to download updates.'''

    def __init__(self, update_info, parent=None):
        '''Initialize update dialog.

        Args:
            update_info (dict): Update information from check_connect_version_update
            parent: Parent widget (optional)
        '''
        self.update_info = update_info
        self.parent = parent
        self.dialog = None
        self.user_choice = None

        # Detect current theme
        self.theme = 'light'
        if hasattr(parent, 'theme') and callable(parent.theme):
            self.theme = parent.theme()
        elif hasattr(parent, '_theme'):
            self.theme = parent._theme

    def create_dialog(self):
        '''Create and configure the update dialog.'''
        try:
            from PySide6 import QtCore, QtGui, QtWidgets
        except ImportError:
            from PySide2 import QtCore, QtGui, QtWidgets

        # Create dialog
        self.dialog = QtWidgets.QDialog(self.parent)
        self.dialog.setWindowTitle('Ftrack Update')
        self.dialog.setFixedSize(520, 280)
        self.dialog.setModal(True)

        # Apply ftrack theme to the dialog
        ftrack_connect.ui.theme.applyTheme(self.dialog, self.theme)

        # Apply ftrack fonts
        ftrack_connect.ui.theme.applyFont()

        # Add custom styles for update dialog elements
        custom_style = """
            QDialog {
                font-family: "Roboto", "Segoe UI", "Arial", sans-serif;
            }
            QLabel#update-icon {
                font-size: 24px;
                font-weight: bold;
                border: 2px solid rgba(19, 25, 32, 0.1);
                border-radius: 24px;
                background-color: rgba(19, 25, 32, 0.05);
                font-family: "Roboto", "Segoe UI", "Arial", sans-serif;
            }
        """

        current_style = self.dialog.styleSheet()
        self.dialog.setStyleSheet(current_style + custom_style)

        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self.dialog)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        # Header section
        header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 20)
        header_layout.setSpacing(15)

        # Update icon (using ftrack icon font if available)
        icon_label = QtWidgets.QLabel("↑")
        icon_label.setFixedSize(48, 48)
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        icon_label.setObjectName('update-icon')

        # Header text
        header_text_layout = QtWidgets.QVBoxLayout()
        header_text_layout.setSpacing(5)

        title_label = QtWidgets.QLabel("Update Available")
        title_label.setObjectName('title')

        subtitle_label = QtWidgets.QLabel(
            f"A newer version v{self.update_info['latest_version']} is ready to install "
            f"(Current v{self.update_info['current_version']})"
        )

        header_text_layout.addWidget(title_label)
        header_text_layout.addWidget(subtitle_label)

        header_layout.addWidget(icon_label)
        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()

        main_layout.addWidget(header_widget)

        # Benefits section - use release notes if available
        benefits_text = self._format_release_notes()
        benefits_label = QtWidgets.QLabel(benefits_text)
        benefits_label.setWordWrap(True)
        benefits_label.setMaximumHeight(
            100
        )  # Limit height to prevent dialog from growing too large
        main_layout.addWidget(benefits_label)

        # Spacer
        main_layout.addStretch()

        # Button section
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(12)

        # Skip button
        skip_button = QtWidgets.QPushButton('Skip')
        skip_button.setFixedSize(80, 35)
        skip_button.clicked.connect(self._on_skip_clicked)

        # Later button
        later_button = QtWidgets.QPushButton('Later')
        later_button.setFixedSize(80, 35)
        later_button.clicked.connect(self._on_continue_clicked)

        # Primary update button
        update_button = QtWidgets.QPushButton('Update')
        update_button.setFixedSize(120, 35)
        update_button.setObjectName('primary')
        update_button.clicked.connect(self._on_auto_update_clicked)

        button_layout.addWidget(skip_button)
        button_layout.addWidget(later_button)
        button_layout.addStretch()
        button_layout.addWidget(update_button)

        main_layout.addLayout(button_layout)

        return self.dialog

    def _format_release_notes(self):
        '''Format release notes for display in the dialog.

        Returns:
            str: Formatted release notes text
        '''
        release_notes = self.update_info.get('release_notes', '')

        if not release_notes or not release_notes.strip():
            # Fallback to generic benefits if no release notes available
            return (
                "• New features and improvements\n"
                "• Bug fixes and stability enhancements"
            )

        # Parse and format the release notes
        formatted_notes = self._parse_markdown_to_bullets(release_notes)

        # Limit to first 4-5 items to prevent dialog from getting too tall
        lines = formatted_notes.split('\n')
        if len(lines) > 5:
            lines = lines[:4] + ['• ...and more improvements']

        return '\n'.join(lines)

    def _parse_markdown_to_bullets(self, markdown_text):
        '''Parse markdown release notes to bullet points.

        Args:
            markdown_text (str): Raw markdown text from GitHub release

        Returns:
            str: Formatted bullet points
        '''
        lines = markdown_text.strip().split('\n')
        bullet_points = []

        for line in lines:
            line = line.strip()

            # Skip empty lines and headers
            if not line or line.startswith('#'):
                continue

            # Convert markdown list items to bullet points
            if line.startswith('- ') or line.startswith('* '):
                # Remove markdown list syntax and add bullet
                clean_line = line[2:].strip()
                if clean_line:
                    bullet_points.append(f'• {clean_line}')
            elif line.startswith('## '):
                # Section headers - ignore for now
                continue
            elif (
                line and not line.startswith('![') and not line.startswith('[')
            ):
                # Regular text lines that aren't images or links
                if len(line) < 100:  # Only include short descriptive lines
                    bullet_points.append(f'• {line}')

        # If we couldn't parse any bullet points, try to extract key phrases
        if not bullet_points:
            # Look for common improvement keywords
            keywords = [
                'fix',
                'add',
                'improve',
                'update',
                'enhance',
                'support',
                'new',
            ]
            for line in lines:
                line = line.strip().lower()
                if (
                    any(keyword in line for keyword in keywords)
                    and len(line) < 100
                ):
                    bullet_points.append(f'• {line.capitalize()}')

        # Final fallback
        if not bullet_points:
            return (
                "• New features and improvements\n"
                "• Bug fixes and stability enhancements\n"
                "• Latest security updates"
            )

        return '\n'.join(bullet_points[:5])  # Limit to 5 items

    def _get_platform_specific_download_url(self):
        '''Get the appropriate download URL for the current platform.

        Returns:
            str: Platform-specific download URL, or None if not found
        '''
        system = platform.system().lower()
        logger.info(f'Getting platform-specific download URL for: {system}')

        # If we have platform-specific URLs in update_info
        if 'download_urls' in self.update_info:
            platform_urls = self.update_info['download_urls']
            logger.info(f'Available platform URLs: {platform_urls}')
            if system == 'darwin' and 'macos' in platform_urls:
                logger.info(f'Using macOS URL: {platform_urls["macos"]}')
                return platform_urls['macos']
            elif system == 'windows' and 'windows' in platform_urls:
                logger.info(f'Using Windows URL: {platform_urls["windows"]}')
                return platform_urls['windows']
            elif system == 'linux' and 'linux' in platform_urls:
                logger.info(f'Using Linux URL: {platform_urls["linux"]}')
                return platform_urls['linux']

        # Fallback: try to modify the single download_url for platform
        base_url = self.update_info.get('download_url', '')
        logger.info(f'Fallback base URL: {base_url}')
        if not base_url:
            return None

        # Try to detect and replace platform-specific parts in the URL
        if system == 'windows':
            # Replace .dmg with .exe for Windows
            if base_url.endswith('.dmg'):
                modified_url = base_url.replace('.dmg', '.exe')
                logger.info(f'Modified URL for Windows: {modified_url}')
                return modified_url
            # Look for macOS-specific patterns and replace with Windows
            base_url = base_url.replace('macos', 'windows').replace(
                'darwin', 'windows'
            )
            if not base_url.endswith(('.exe', '.msi')):
                # Add .exe extension if no Windows extension found
                base_url = base_url.rstrip('/') + '.exe'
        elif system == 'linux':
            # Replace .dmg with appropriate Linux format
            if base_url.endswith('.dmg'):
                return base_url.replace('.dmg', '.tar.gz')
            # Look for macOS-specific patterns and replace with Linux
            base_url = base_url.replace('macos', 'linux').replace(
                'darwin', 'linux'
            )
            if not base_url.endswith(('.tar.gz', '.deb', '.rpm', '.appimage')):
                # Add .tar.gz extension if no Linux extension found
                base_url = base_url.rstrip('/') + '.tar.gz'
        elif system == 'darwin':
            # For macOS, ensure .dmg extension
            if not base_url.endswith('.dmg'):
                base_url = base_url.rstrip('/') + '.dmg'

        logger.info(f'Final URL for {system}: {base_url}')
        return base_url

    def _on_auto_update_clicked(self):
        '''Handle automatic update button click.'''
        if not self.update_info.get('download_url'):
            # Fallback to manual download if no direct download URL
            self._on_manual_download_clicked()
            return

        # Show download progress dialog
        try:
            from PySide6 import QtCore, QtGui, QtWidgets
        except ImportError:
            from PySide2 import QtCore, QtGui, QtWidgets

        progress_dialog = DownloadProgressDialog(self.dialog)
        progress_dialog.show()

        # Create temporary file for download
        download_url = self._get_platform_specific_download_url()
        if not download_url:
            # No platform-specific URL found, fallback to manual download
            self._on_manual_download_clicked()
            return

        file_extension = os.path.splitext(download_url)[1]
        if not file_extension:
            # Guess extension based on platform
            system = platform.system().lower()
            if system == 'darwin':
                file_extension = '.dmg'
            elif system == 'windows':
                file_extension = '.exe'
            else:
                file_extension = '.tar.gz'

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=file_extension,
            prefix=f'ftrack-connect-{self.update_info["latest_version"]}-',
        )
        temp_file.close()

        def progress_callback(progress, status):
            if not progress_dialog.cancelled:
                progress_dialog.update_progress(progress, status)
                QtCore.QCoreApplication.processEvents()

        try:
            # Download the update
            logger.info(f'Downloading update from: {download_url}')
            progress_dialog.update_progress(0, 'Starting download...')

            success = download_file_with_progress(
                download_url, temp_file.name, progress_callback
            )

            if progress_dialog.cancelled:
                # User cancelled download
                progress_dialog.close()
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
                return

            if success:
                progress_dialog.update_progress(
                    100, 'Download complete! Installing...'
                )
                QtCore.QCoreApplication.processEvents()

                # Install the update with progress updates - but don't actually install yet
                def install_progress_callback(step, message):
                    if not progress_dialog.cancelled:
                        # For download phase, we're just preparing
                        step_progress = {
                            'preparing': 10,
                            'ready': 100,
                        }
                        progress = step_progress.get(step, 50)
                        progress_dialog.update_progress(progress, message)
                        QtCore.QCoreApplication.processEvents()

                # Instead of installing immediately, just prepare for deferred installation
                progress_dialog.update_progress(10, 'Preparing installation...')
                QtCore.QCoreApplication.processEvents()

                progress_dialog.update_progress(100, 'Ready to install!')
                QtCore.QCoreApplication.processEvents()

                install_success = (
                    True  # We've successfully downloaded and are ready
                )

                progress_dialog.close()

                if install_success:
                    # Show success message and prepare for restart
                    msg_box = QtWidgets.QMessageBox(self.dialog)
                    msg_box.setWindowTitle('Update Ready')
                    msg_box.setIcon(QtWidgets.QMessageBox.Information)
                    msg_box.setText('Update downloaded successfully!')
                    msg_box.setInformativeText(
                        'The update has been downloaded and is ready to install.\n\n'
                        'Ftrack will close and the installer will run.\n'
                        'Please follow the installation instructions and then restart Ftrack.'
                    )

                    # Apply ftrack theme to the message box
                    ftrack_connect.ui.theme.applyTheme(msg_box, self.theme)

                    install_button = msg_box.addButton(
                        'Install',
                        QtWidgets.QMessageBox.ActionRole,
                    )
                    install_button.setObjectName('primary')
                    msg_box.setDefaultButton(install_button)

                    # Add a cancel button so user can close without installing
                    cancel_button = msg_box.addButton(
                        'Cancel',
                        QtWidgets.QMessageBox.RejectRole,
                    )

                    result = msg_box.exec_()

                    # Log the download details for debugging
                    logger.info(f'Downloaded installer: {temp_file.name}')
                    logger.info(f'Download URL was: {download_url}')

                    # Only proceed with installation if user clicked the install button
                    if msg_box.clickedButton() == install_button:
                        # Start the installer and prepare to exit Ftrack
                        self._start_deferred_installation(temp_file.name)
                        self.user_choice = 'auto_updated'
                        self.dialog.accept()
                    # If user cancelled or closed dialog, just clean up temp file
                    else:
                        try:
                            os.unlink(temp_file.name)
                        except:
                            pass

                else:
                    # Installation failed, offer manual option
                    msg_box = QtWidgets.QMessageBox(self.dialog)
                    msg_box.setWindowTitle('Installation Error')
                    msg_box.setIcon(QtWidgets.QMessageBox.Warning)
                    msg_box.setText('Automatic installation failed.')
                    msg_box.setInformativeText(
                        f'The update was downloaded successfully but automatic installation failed.\n\n'
                        f'You can install it manually:\n'
                        f'1. Double-click the downloaded DMG file, or\n'
                        f'2. Use the "Open DMG File" button below\n'
                        f'3. Drag Ftrack to Applications folder\n'
                        f'4. Restart Ftrack\n\n'
                        f'DMG location: {temp_file.name}'
                    )

                    # Apply ftrack theme to the message box
                    ftrack_connect.ui.theme.applyTheme(msg_box, self.theme)

                    open_dmg_button = msg_box.addButton(
                        'Open DMG File', QtWidgets.QMessageBox.ActionRole
                    )
                    manual_button = msg_box.addButton(
                        'Open Download Folder', QtWidgets.QMessageBox.ActionRole
                    )
                    retry_button = msg_box.addButton(
                        'Try Again', QtWidgets.QMessageBox.ActionRole
                    )
                    cancel_button = msg_box.addButton(
                        'Cancel', QtWidgets.QMessageBox.RejectRole
                    )

                    msg_box.exec_()

                    if msg_box.clickedButton() == open_dmg_button:
                        # Open the DMG file directly
                        subprocess.run(['open', temp_file.name])
                        self.user_choice = 'manual_install'
                        self.dialog.accept()
                    elif msg_box.clickedButton() == manual_button:
                        # Open download folder
                        system = platform.system().lower()
                        if system == 'darwin':
                            subprocess.run(
                                ['open', os.path.dirname(temp_file.name)]
                            )
                        elif system == 'windows':
                            subprocess.run(
                                ['explorer', os.path.dirname(temp_file.name)]
                            )
                        elif system == 'linux':
                            subprocess.run(
                                ['xdg-open', os.path.dirname(temp_file.name)]
                            )
                        self.user_choice = 'manual_install'
                        self.dialog.accept()
                    elif msg_box.clickedButton() == retry_button:
                        # Retry automatic installation
                        self._on_auto_update_clicked()
                        return
            else:
                progress_dialog.close()
                # Download failed
                msg_box = QtWidgets.QMessageBox(self.dialog)
                msg_box.setWindowTitle('Download Error')
                msg_box.setIcon(QtWidgets.QMessageBox.Critical)
                msg_box.setText('Failed to download update.')
                msg_box.setInformativeText(
                    'There was an error downloading the update. Please check your '
                    'internet connection and try again, or download manually.'
                )

                # Apply ftrack theme to the message box
                ftrack_connect.ui.theme.applyTheme(msg_box, self.theme)

                retry_button = msg_box.addButton(
                    'Try Again', QtWidgets.QMessageBox.ActionRole
                )
                manual_button = msg_box.addButton(
                    'Download Manually', QtWidgets.QMessageBox.ActionRole
                )
                cancel_button = msg_box.addButton(
                    'Cancel', QtWidgets.QMessageBox.RejectRole
                )

                msg_box.exec_()

                if msg_box.clickedButton() == retry_button:
                    self._on_auto_update_clicked()
                    return
                elif msg_box.clickedButton() == manual_button:
                    self._on_manual_download_clicked()
                    return

        except Exception as e:
            progress_dialog.close()
            logger.error(f'Error during automatic update: {e}')

            msg_box = QtWidgets.QMessageBox(self.dialog)
            msg_box.setWindowTitle('Update Error')
            msg_box.setIcon(QtWidgets.QMessageBox.Critical)
            msg_box.setText('An error occurred during the update process.')
            msg_box.setInformativeText(f'Error: {str(e)}')

            # Apply ftrack theme to the message box
            ftrack_connect.ui.theme.applyTheme(msg_box, self.theme)

            msg_box.exec_()

    def _start_deferred_installation(self, installer_path):
        '''Start deferred installation that runs after Ftrack exits.

        Args:
            installer_path (str): Path to the installer file (DMG, EXE, etc.)
        '''
        try:
            system = platform.system().lower()

            if system == 'darwin':  # macOS
                # Create a bash script that will wait for Ftrack to exit and then install
                script_content = f'''#!/bin/bash
# Wait for Ftrack process to exit
echo "Waiting for Ftrack to exit..."
while pgrep -f "ftrack_connect" > /dev/null; do
    sleep 1
done

echo "Installing Ftrack update..."
# Open the DMG file (macOS will handle mounting and showing the installer)
open "{installer_path}"

# Optionally, we could try to automate the installation, but opening the DMG
# is safer and gives the user control
echo "Update installer opened. Please follow the installation instructions."
'''

                # Write the script to a temporary file
                script_file = tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.sh',
                    delete=False,
                    prefix='ftrack_connect_update_',
                )
                script_file.write(script_content)
                script_file.close()

                # Make the script executable
                os.chmod(script_file.name, 0o755)

                # Start the script in the background
                subprocess.Popen(
                    ['bash', script_file.name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                logger.info(
                    f'Deferred installation script started: {script_file.name}'
                )

            elif system == 'windows':  # Windows
                # Create a batch script that will wait for Ftrack to exit and then install
                script_content = f'''@echo off
echo Waiting for Ftrack to exit...
:wait_loop
tasklist /FI "IMAGENAME eq ftrack_connect*" 2>NUL | find /I /N "ftrack_connect" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 >nul
    goto wait_loop
)

echo Installing Ftrack update...
start "" "{installer_path}"
echo Update installer opened. Please follow the installation instructions.
'''

                # Write the script to a temporary file
                script_file = tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.bat',
                    delete=False,
                    prefix='ftrack_connect_update_',
                )
                script_file.write(script_content)
                script_file.close()

                # Start the script in the background
                subprocess.Popen(
                    [script_file.name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

                logger.info(
                    f'Deferred installation script started: {script_file.name}'
                )

            elif system == 'linux':  # Linux
                # Create a shell script that will wait for Ftrack to exit and then install
                script_content = f'''#!/bin/bash
# Wait for Ftrack process to exit
echo "Waiting for Ftrack to exit..."
while pgrep -f "ftrack_connect" > /dev/null; do
    sleep 1
done

echo "Installing Ftrack update..."
# Open the installer file with the default application
xdg-open "{installer_path}"

echo "Update installer opened. Please follow the installation instructions."
'''

                # Write the script to a temporary file
                script_file = tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.sh',
                    delete=False,
                    prefix='ftrack_connect_update_',
                )
                script_file.write(script_content)
                script_file.close()

                # Make the script executable
                os.chmod(script_file.name, 0o755)

                # Start the script in the background
                subprocess.Popen(
                    ['bash', script_file.name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                logger.info(
                    f'Deferred installation script started: {script_file.name}'
                )

            else:
                # Unsupported platform, fallback to just opening the file
                logger.warning(f'Unsupported platform: {system}')
                raise Exception(f'Unsupported platform: {system}')

        except Exception as e:
            logger.error(f'Error starting deferred installation: {e}')
            # Fallback to just opening the installer file directly
            system = platform.system().lower()
            if system == 'darwin':
                subprocess.run(['open', installer_path])
            elif system == 'windows':
                subprocess.run(['start', '', installer_path], shell=True)
            elif system == 'linux':
                subprocess.run(['xdg-open', installer_path])
            else:
                logger.error(
                    f'Cannot open installer on unsupported platform: {system}'
                )

    def _on_manual_download_clicked(self):
        '''Handle manual download button click.'''
        if self.update_info.get('download_url'):
            logger.info(
                f'Opening download URL: {self.update_info["download_url"]}'
            )
            webbrowser.open(self.update_info['download_url'])
        else:
            # Fallback to GitHub releases page
            webbrowser.open('https://github.com/it-mana/integrations/releases')

        self.user_choice = 'manual_download'
        self.dialog.accept()

    def _on_skip_clicked(self):
        '''Handle skip button click.'''
        self.user_choice = 'skip'
        self.dialog.accept()

    def _on_continue_clicked(self):
        '''Handle continue button click.'''
        self.user_choice = 'continue'
        self.dialog.accept()

    def show_dialog(self):
        '''Show the update dialog and return user choice.

        Returns:
            str: User choice ('download', 'skip', or 'continue')
        '''
        try:
            from PySide6 import QtWidgets
        except ImportError:
            from PySide2 import QtWidgets

        if not self.dialog:
            self.create_dialog()

        result = self.dialog.exec_()

        if result == QtWidgets.QDialog.Rejected:
            # Dialog was closed without clicking a button
            self.user_choice = 'continue'

        return self.user_choice


def show_update_dialog(update_info, parent=None):
    '''Show update dialog and return user choice.

    Args:
        update_info (dict): Update information from check_connect_version_update
        parent: Parent widget (optional)

    Returns:
        str: User choice ('download', 'skip', or 'continue')
    '''
    dialog = UpdateDialog(update_info, parent)
    return dialog.show_dialog()
