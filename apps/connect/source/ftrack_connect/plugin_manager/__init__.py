# :coding: utf-8
# :copyright: Copyright (c) 2014-2024 ftrack
import platform
import traceback
import qtawesome as qta
import os
import logging

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui

from ftrack_connect.utils.thread import qt_main_thread
from ftrack_connect.utils.plugin import PLUGIN_DIRECTORIES

from ftrack_connect.ui.widget.overlay import BlockingOverlay, BusyOverlay
import ftrack_connect.ui.application

from ftrack_utils.decorators import asynchronous
from ftrack_utils.usage import get_usage_tracker

from ftrack_connect.plugin_manager.overlay import InstallerBlockingOverlay
from ftrack_connect.plugin_manager.processor import PluginProcessor, ROLES
from ftrack_connect.plugin_manager.plugin_list import DndPluginList
from ftrack_connect.plugin_manager.welcome import WelcomeDialog

logger = logging.getLogger(__name__)


class PluginManager(ftrack_connect.ui.application.ConnectWidget):
    '''Show and manage plugin installations.'''

    name = 'Plugins'

    show_welcome = QtCore.Signal(
        object
    )  # Number of downloadable plugins as argument

    installation_done = QtCore.Signal()
    installation_started = QtCore.Signal()
    installation_in_progress = QtCore.Signal(object)
    installation_failed = QtCore.Signal(object)

    refresh_started = QtCore.Signal()
    refresh_done = QtCore.Signal()

    apply_changes = QtCore.Signal(object)
    # List of plugins to archive as argument

    @property
    def items(self):
        '''Return items in plugin list.'''
        result = []
        num_items = self._plugin_list_widget.plugin_model.rowCount()
        for i in range(num_items):
            item = self._plugin_list_widget.plugin_model.item(i)
            result.append(item)
        return result

    @property
    def installed_plugins(self):
        '''Return list of installed plugins'''
        return self._installed_plugins

    # default methods
    def __init__(self, session, parent=None):
        '''Instantiate the plugin widget.'''
        super(PluginManager, self).__init__(session, parent=parent)
        self._label = None
        self._select_release_type_widget = None
        self._search_bar = None
        self._plugin_list_widget = None
        self._button_layout = None
        self._apply_button = None
        self._reset_button = None
        self._welcome_dialog = None
        self._blocking_overlay = None
        self._busy_overlay = None
        self._plugins_to_install = None
        self._counter = 0
        self._initialised = False
        self._installed_plugins = None

        self._reset_plugin_list()
        self._plugin_processor = PluginProcessor()

        self.pre_build()
        self.build()
        self.post_build()

    def pre_build(self):
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

    def build(self):
        self._search_bar = QtWidgets.QLineEdit()
        self._search_bar.setPlaceholderText('Search plugin...')

        self.layout().addWidget(self._search_bar)
        self._label = QtWidgets.QLabel(
            'Check the plugins you want to install or add your'
            ' local plugins by dropping them on the list below'
        )
        self._label.setWordWrap(True)
        self._label.setMargin(5)
        self.layout().addWidget(self._label)

        # choose release type
        self._select_release_type_widget = QtWidgets.QCheckBox(
            'Show pre-releases'
        )
        self.layout().addWidget(self._select_release_type_widget)
        # plugin list
        self._plugin_list_widget = DndPluginList()
        self.layout().addWidget(self._plugin_list_widget)

        # apply and reset button.
        self._button_layout = QtWidgets.QHBoxLayout()

        self._apply_button = QtWidgets.QPushButton('Install Plugins')
        self._apply_button.setIcon(QtGui.QIcon(qta.icon('mdi6.check')))
        self._apply_button.setDisabled(True)

        self._reset_button = QtWidgets.QPushButton('Clear selection')
        self._reset_button.setIcon(QtGui.QIcon(qta.icon('mdi6.lock-reset')))
        self._reset_button.setMaximumWidth(120)

        self._button_layout.addWidget(self._apply_button)
        self._button_layout.addWidget(self._reset_button)

        self.layout().addLayout(self._button_layout)

        self._welcome_dialog = WelcomeDialog(
            self._on_install_all_callback, self._on_restart_callback
        )
        self._welcome_dialog.hide()
        self.layout().addWidget(self._welcome_dialog)

        # overlays
        self._blocking_overlay = InstallerBlockingOverlay(self)
        self._blocking_overlay.hide()

        self._busy_overlay = BusyOverlay(self, 'Updating....')
        self._busy_overlay.hide()

    def post_build(self):
        # wire connections
        self._select_release_type_widget.clicked.connect(
            self._on_select_release_type_callback
        )
        self._apply_button.clicked.connect(self._on_apply_changes)
        self._reset_button.clicked.connect(self.refresh)
        self._search_bar.textChanged.connect(
            self._plugin_list_widget.proxy_model.setFilterFixedString
        )
        self.show_welcome.connect(self._on_show_welcome_callback)
        self.apply_changes.connect(self.on_apply_changes_confirmed_callback)
        self.installation_started.connect(self._busy_overlay.show)
        self.installation_done.connect(self._busy_overlay.hide)
        self.installation_done.connect(self._show_user_message_done)
        self.installation_failed.connect(self._busy_overlay.hide)
        self.installation_failed.connect(self._show_user_message_failed)

        self.installation_done.connect(self._reset_overlay)
        self.installation_in_progress.connect(self._update_overlay)

        self.refresh_started.connect(self._busy_overlay.show)
        self.refresh_done.connect(self._busy_overlay.hide)

        self._plugin_list_widget.plugin_model.itemChanged.connect(
            self._enable_apply_button
        )

        self._blocking_overlay.confirm_button.clicked.connect(self.refresh)
        self._blocking_overlay.restart_button.clicked.connect(
            self._on_restart_callback
        )

    def _on_restart_callback(self):
        self.requestConnectRestart.emit()

    def _reset_plugin_list(self):
        self._counter = 0
        self._plugins_to_install = []

    def _emit_downloaded_plugins(self, plugins):
        metadata = {'installed_plugins': []}

        for plugin in plugins:
            name = str(plugin.data(ROLES.PLUGIN_NAME))
            version = str(plugin.data(ROLES.PLUGIN_VERSION))
            _os = str(platform.platform())

            plugin_data = {'name': name, 'version': version, 'os': _os}
            metadata['installed_plugins'].append(plugin_data)

        usage_tracker = get_usage_tracker()
        if usage_tracker:
            usage_tracker.track("INSTALLED-CONNECT-PLUGINS", metadata)

    @qt_main_thread
    def _enable_apply_button(self, item):
        '''Check the plugins state.'''
        self._apply_button.setDisabled(True)
        items = []
        for index in range(self._plugin_list_widget.plugin_model.rowCount()):
            if (
                self._plugin_list_widget.plugin_model.item(index).checkState()
                == QtCore.Qt.CheckState.Checked
            ):
                items.append(self._plugin_list_widget.plugin_model.item(index))

        self._plugins_to_install = items

        if items:
            self._apply_button.setEnabled(True)

        self._apply_button.setText(
            f'Install {len(self._plugins_to_install)} Plugins'
        )

    @asynchronous
    def refresh(self):
        '''Force refresh of the model, fetching all the available plugins. This
        function is run in a separate thread, make sure that UI alterations are
        performed in QT main thread.'''
        self.refresh_started.emit()
        self.fetchPlugins.emit(self._on_plugin_fetch_callback)
        self._enable_apply_button(None)
        self._reset_plugin_list()
        self.refresh_done.emit()
        self._initialised = False

    def _on_plugin_fetch_callback(self, plugins):
        '''Callback on fetching installed plugins from Connect'''
        self._installed_plugins = plugins
        self._plugin_list_widget.populate_installed_plugins(plugins)
        self._plugin_list_widget.populate_download_plugins(
            self._select_release_type_widget.isChecked()
        )
        
        # Check for auto-install/update regardless of how many plugins are installed
        self._check_and_run_auto_operations()
        
        if (
            not self._initialised
            and len(self._plugin_list_widget.installed_plugins) == 0
        ):
            disable_startup_widget = bool(
                os.getenv('FTRACK_CONNECT_DISABLE_STARTUP_WIDGET', False)
            )
            if not disable_startup_widget:
                self.show_welcome.emit(
                    self._plugin_list_widget.downloadable_plugin_count
                )

    def _check_and_run_auto_operations(self):
        '''Check if auto-install or auto-update is enabled and run them.'''
        # Only run auto operations once per session
        if self._initialised:
            return
            
        # Check if auto-install or auto-update is enabled via environment variable
        auto_install = "true"
        auto_update = "true"

        if auto_install in ['true', '1', 'yes'] or auto_update in ['true', '1', 'yes']:
            downloadable_plugin_count = self._plugin_list_widget.downloadable_plugin_count
            
            if auto_install in ['true', '1', 'yes']:
                logger.info(f'Auto-installing {downloadable_plugin_count} available plugins...')
            
            if auto_update in ['true', '1', 'yes']:
                update_count = self._count_plugin_updates()
                logger.info(f'Auto-updating {update_count} plugins with newer versions...')
            
            # Only proceed if there are plugins to process
            total_to_process = self._count_plugins_to_process(
                auto_install in ['true', '1', 'yes'], 
                auto_update in ['true', '1', 'yes']
            )
            
            if total_to_process > 0:
                logger.info(f'Starting auto-processing of {total_to_process} plugins...')
                
                # Automatically install/update all plugins
                def plugin_processed_callback(index, total, action, plugin_info):
                    logger.info(f'{action} {index}/{total} plugins: {plugin_info}')
                
                self._on_auto_install_update_callback(
                    plugin_processed_callback, 
                    auto_install in ['true', '1', 'yes'], 
                    auto_update in ['true', '1', 'yes']
                )
                logger.info('Auto-installation/update of plugins completed')
            else:
                logger.info('No plugins to auto-install or auto-update.')
        
        # Mark as initialized to prevent running auto operations again
        self._initialised = True

    def _on_show_welcome_callback(self, downloadable_plugin_count):
        # Show dialog were user can choose to install all available plugins
        # Execute dialog and evaluate response
        # Show warning dialog
        if downloadable_plugin_count == 0:
            QtWidgets.QMessageBox.warning(
                self,
                'Plugin Manager',
                'No plugins installed and no downloadable plugins found! Please check your configuration.',
            )
            return

        # Check if auto-install or auto-update is enabled via environment variable
        # auto_install = os.environ.get('FTRACK_CONNECT_AUTO_INSTALL_PLUGINS', '').lower()
        # auto_update = os.environ.get('FTRACK_CONNECT_AUTO_UPDATE_PLUGINS', '').lower()
        auto_install = "true"
        auto_update = "true"

        if auto_install in ['true', '1', 'yes'] or auto_update in ['true', '1', 'yes']:
            if auto_install in ['true', '1', 'yes']:
                logger.info(f'Auto-installing {downloadable_plugin_count} available plugins...')
            
            if auto_update in ['true', '1', 'yes']:
                update_count = self._count_plugin_updates()
                logger.info(f'Auto-updating {update_count} plugins with newer versions...')
            
            # Automatically install/update all plugins without showing the welcome dialog
            def plugin_processed_callback(index, total, action, plugin_info):
                logger.info(f'{action} {index}/{total} plugins: {plugin_info}')
            
            self._on_auto_install_update_callback(
                plugin_processed_callback, 
                auto_install in ['true', '1', 'yes'], 
                auto_update in ['true', '1', 'yes']
            )
            logger.info('Auto-installation/update of plugins completed')
            return

        self._label.setVisible(False)
        self._search_bar.setVisible(False)
        self._plugin_list_widget.setVisible(False)
        self._reset_button.setVisible(False)
        self._apply_button.setVisible(False)
        self._welcome_dialog.set_downloadable_plugin_count(
            downloadable_plugin_count
        )
        self._welcome_dialog.exec_()
        self._welcome_dialog.hide()
        self._label.setVisible(True)
        self._search_bar.setVisible(True)
        self._plugin_list_widget.setVisible(True)
        self._reset_button.setVisible(True)
        self._apply_button.setVisible(True)

    def _on_install_all_callback(self, on_plugin_installed_callback):
        '''Install all downloadable plugins, to be called from welcome dialog'''
        num_items = self._plugin_list_widget.plugin_model.rowCount()
        for i in range(num_items):
            item = self._plugin_list_widget.plugin_model.item(i)
            self._plugin_processor.process(item)
            on_plugin_installed_callback(i + 1)
        self._reset_plugin_list()

    def _count_plugin_updates(self):
        '''Count how many plugins have newer versions available.'''
        update_count = 0
        num_items = self._plugin_list_widget.plugin_model.rowCount()
        
        for i in range(num_items):
            item = self._plugin_list_widget.plugin_model.item(i)
            status = item.data(ROLES.PLUGIN_STATUS)
            
            # Count UPDATE status plugins
            if status == 2:  # STATUSES.UPDATE
                update_count += 1
        
        return update_count

    def _count_plugins_to_process(self, do_install, do_update):
        '''Count how many plugins will be processed with the given settings.'''
        from ftrack_connect.plugin_manager.processor import STATUSES
        
        count = 0
        num_items = self._plugin_list_widget.plugin_model.rowCount()
        
        for i in range(num_items):
            item = self._plugin_list_widget.plugin_model.item(i)
            status = item.data(ROLES.PLUGIN_STATUS)
            
            if status == STATUSES.NEW and do_install:
                count += 1
            elif status == STATUSES.UPDATE and do_update:
                count += 1
            elif status == STATUSES.DOWNLOAD:
                if do_install:  # DOWNLOAD status treated as new install
                    count += 1
        
        return count

    def _is_newer_version(self, available_version, installed_version):
        '''Compare version strings to determine if available version is newer.
        
        Args:
            available_version (str): Version available for download
            installed_version (str): Currently installed version
            
        Returns:
            bool: True if available version is newer
        '''
        try:
            from packaging.version import parse as parse_version
            return parse_version(str(available_version)) > parse_version(str(installed_version))
        except Exception:
            # Fallback to string comparison if packaging is not available
            return str(available_version) > str(installed_version)

    def _on_auto_install_update_callback(self, on_plugin_processed_callback, do_install=True, do_update=True):
        '''Automatically install new plugins and/or update existing ones.
        
        Args:
            on_plugin_processed_callback: Callback function for progress updates
            do_install (bool): Whether to install new plugins
            do_update (bool): Whether to update existing plugins
        '''
        from ftrack_connect.plugin_manager.processor import STATUSES
        
        num_items = self._plugin_list_widget.plugin_model.rowCount()
        processed_count = 0
        
        # Get plugins to process
        plugins_to_process = []
        
        for i in range(num_items):
            item = self._plugin_list_widget.plugin_model.item(i)
            status = item.data(ROLES.PLUGIN_STATUS)
            plugin_name = item.data(ROLES.PLUGIN_NAME)
            available_version = item.data(ROLES.PLUGIN_VERSION)
            
            # Determine what action to take
            action = None
            version_info = f'v{available_version}'
            
            if status == STATUSES.NEW and do_install:
                action = 'Installing'
                plugins_to_process.append((item, action, plugin_name, version_info))
            elif status == STATUSES.UPDATE and do_update:
                action = 'Updating'
                # For updates, try to get the current version info
                for installed_plugin in self._installed_plugins:
                    if installed_plugin['name'] == plugin_name:
                        installed_version = installed_plugin.get('version', '0.0.0')
                        version_info = f'{installed_version} -> {available_version}'
                        break
                plugins_to_process.append((item, action, plugin_name, version_info))
            elif status == STATUSES.DOWNLOAD:
                # DOWNLOAD status could be either new or update depending on do_install/do_update
                if do_install:
                    action = 'Installing'
                    plugins_to_process.append((item, action, plugin_name, version_info))
        
        total_to_process = len(plugins_to_process)
        
        if total_to_process == 0:
            logger.info('No plugins to install or update.')
            return
        
        logger.info(f'Processing {total_to_process} plugins...')
        
        # Process the plugins
        for item, action, plugin_name, version_info in plugins_to_process:
            try:
                processed_count += 1
                logger.info(f'{action} plugin {processed_count}/{total_to_process}: {plugin_name} ({version_info})')
                
                # Process the plugin
                self._plugin_processor.process(item)
                
                # Call the progress callback
                on_plugin_processed_callback(processed_count, total_to_process, action, f'{plugin_name} ({version_info})')
                
            except Exception as e:
                logger.error(f'Failed to {action.lower()} plugin {plugin_name}: {str(e)}')
                continue
        
        self._reset_plugin_list()
        logger.info(f'Successfully processed {processed_count}/{total_to_process} plugins')
        
        # If any plugins were processed, notify user about restart requirement
        if processed_count > 0:
            self._show_auto_install_restart_message(processed_count, total_to_process, plugins_to_process)

    def _show_auto_install_restart_message(self, processed_count, total_count, plugins_processed):
        '''Show restart message after auto-installing/updating plugins.'''
        
        # Build the plugin list text
        plugin_list_text = ""
        if plugins_processed:
            plugin_list_text = "\n\nProcessed plugins:\n"
            for item, action, plugin_name, version_info in plugins_processed:
                plugin_list_text += f"• {action}: {plugin_name} ({version_info})\n"
        
        message_text = (
            f'Successfully processed {processed_count} of {total_count} plugins.'
            f'{plugin_list_text}\n'
            'ftrack Connect needs to restart to load the new plugins.\n\n'
            'Would you like to restart now?'
        )
        
        msgbox = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Information,
            'Plugin Installation Complete',
            message_text,
            buttons=QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            parent=self,
        )
        answer = msgbox.exec_()
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.requestConnectRestart.emit()

    def _on_select_release_type_callback(self):
        self._reset_button.click()

    def _show_user_message_done(self):
        '''Show final message to the user.'''
        self._blocking_overlay.message = '<h2>Installation finished!</h2>'
        self._blocking_overlay.icon_data = qta.icon(
            'mdi6.check', color='#FFDD86', scale_factor=1.2
        )
        self._blocking_overlay.confirm_button.show()
        self._blocking_overlay.show()

    def _show_user_message_failed(self, reason):
        '''Show final message to the user.'''
        self._blocking_overlay.message = '<h2>Installation FAILED!</h2>'
        self._blocking_overlay.icon_data = qta.icon(
            'mdi6.close', color='#FF8686', scale_factor=1.2
        )
        self._blocking_overlay.set_reason(reason)
        self._blocking_overlay.confirm_button.show()
        self._blocking_overlay.show()

    def _reset_overlay(self):
        self._reset_plugin_list()
        self._busy_overlay.message = '<h2>Updating....</h2>'

    def _update_overlay(self, item):
        '''Update the overlay'''
        self._counter += 1

        self._busy_overlay.message = (
            f'<h2>Installing {self._counter} of {len(self._plugins_to_install)} plugins...</h2></br>'
            f'{item.data(ROLES.PLUGIN_NAME)}, Version {str(item.data(ROLES.PLUGIN_VERSION))}'
        )

    def _get_incompatible_plugin_names(self):
        result = []
        for plugin in self.installed_plugins:
            if plugin['incompatible']:
                result.append(plugin['name'])
        return result

    def _get_deprecated_plugin_names(self):
        result = []
        for plugin in self.installed_plugins:
            if plugin['deprecated']:
                result.append(plugin['name'])
        return result

    def _on_apply_changes(self):
        '''User wants to apply the updates, warn about conflicting plugins.'''
        incompatible_plugin_names = self._get_incompatible_plugin_names()
        deprecated_plugins = self._get_deprecated_plugin_names()
        if incompatible_plugin_names:
            msgbox = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Icon.Warning,
                'Warning',
                'The following conflicting and incompatible plugins are installed and will be ignored by Connect'
                ':\n\n{}\n\nClean up and archive them?\n\n Note: you might want to keep them if you are still using Connect 2'.format(
                    '\n'.join(incompatible_plugin_names)
                ),
                buttons=QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                parent=self,
            )
            answer = msgbox.exec_()
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                pass
            elif answer == QtWidgets.QMessageBox.StandardButton.No:
                incompatible_plugin_names = []  # Keep them
            elif answer == QtWidgets.QMessageBox.StandardButton.Cancel:
                return
        if deprecated_plugins:
            msgbox = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Icon.Warning,
                'Warning',
                'The following deprecated plugins are installed'
                ':\n\n{}\n\nClean up and archive them?\n\nNote: they might still function, please '
                'check release notes for further details. You might want to keep them if you are still using Connect 2'.format(
                    '\n'.join(deprecated_plugins)
                ),
                buttons=QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                parent=self,
            )
            answer = msgbox.exec_()
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                pass
            elif answer == QtWidgets.QMessageBox.StandardButton.No:
                deprecated_plugins = []  # Keep them
            else:
                return
        self.apply_changes.emit(incompatible_plugin_names + deprecated_plugins)

    @asynchronous
    def on_apply_changes_confirmed_callback(self, archive_plugins):
        '''Will process all the selected plugins.'''
        # Check if any conflicting plugins are installed.
        self.installation_started.emit()
        try:
            for plugin in archive_plugins:
                self._plugin_list_widget.archive_legacy_plugin(plugin)
            num_items = self._plugin_list_widget.plugin_model.rowCount()
            for i in range(num_items):
                item = self._plugin_list_widget.plugin_model.item(i)
                if item.checkState() == QtCore.Qt.CheckState.Checked:
                    self.installation_in_progress.emit(item)
                    self._plugin_processor.process(item)
            self.installation_done.emit()
            self._emit_downloaded_plugins(self._plugins_to_install)
            self._reset_plugin_list()
        except:
            # Do not leave the overlay in a bad state.
            self.installation_failed.emit(traceback.format_exc())

    def get_debug_information(self):
        '''Append all identified plugins as debug information.'''
        result = super(PluginManager, self).get_debug_information()
        result['installed_plugins'] = []
        for item in self.items:
            result['installed_plugins'].append(item.text())
        return result
