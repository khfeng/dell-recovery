#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# «recovery_builder» - Dell Recovery DVD Creator
#
# Copyright (C) 2010, Dell Inc.
#
# Author:
#  - Mario Limonciello <Mario_Limonciello@Dell.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this application; if not, write to the Free Software Foundation, Inc., 51
# Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
##################################################################################

import os
import sys
import gtk
import subprocess

from Dell.recovery_frontend import GTKFrontend
from Dell.recovery_common import *

try:
    from aptdaemon import client
    from aptdaemon.enums import *
    from aptdaemon.gtkwidgets import (AptErrorDialog,
                                      AptProgressDialog,
                                      AptMessageDialog)
except ImportError:
    pass

#Translation support
import gettext
from gettext import gettext as _

class GTKBuilderFrontend(GTKFrontend):

    def __init__(self,up,rp,version,media,target,overwrite,xrev,branch):
        """Inserts builder widgets into the Gtk.Assistant"""
        try:
            import vte
        except ImportError:
            header = _("python-vte is missing")
            body = _("Builder mode requires python-vte to function")
            self.show_alert(gtk.MESSAGE_ERROR, header, body,
                parent=None)
            sys.exit(1)

        #Run the normal init first
        GTKFrontend.__init__(self,up,rp,version,media,target,overwrite,xrev,branch)

        #Build our extra GUI in
        self.builder_widgets=gtk.Builder()
        self.builder_widgets.add_from_file(os.path.join(UIDIR,'builder.ui'))
        self.builder_widgets.connect_signals(self)

        self.translate_widgets(self.builder_widgets)

        wizard = self.widgets.get_object('wizard')
        #wizard.resize(400,400)
        wizard.set_title(wizard.get_title() + _(" (BTO Image Builder Mode)"))

        self.widgets.get_object('start_page').set_text(_("This application will integrate a Dell \
OEM FID framework & driver package set into a customized \
OS media image.  You will have the option to \
create an USB key or DVD image."))

        self.file_dialog = gtk.FileChooserDialog("Choose Item",
                                           None,
                                           gtk.FILE_CHOOSER_ACTION_OPEN,
                                           (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                            gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        self.file_dialog.set_default_response(gtk.RESPONSE_OK)

        #Set up the VTE window for GIT stuff
        self.builder_widgets.get_object('builder_vte_window').set_transient_for(wizard)
        self.vte = vte.Terminal()
        self.builder_widgets.get_object('fetch_expander').add(self.vte)
        self.vte.show()
        self.vte.connect("child-exited", self.fid_vte_handler)

        #setup the possible dialog for adding dell-recovery package in
        self.builder_widgets.get_object('builder_add_dell_recovery_window').set_transient_for(wizard)

        #popup window for SRVs
        self.builder_widgets.get_object('srv_dialog').set_transient_for(wizard)

        #insert builder pages
        wizard.insert_page(self.builder_widgets.get_object('application_page'),1)
        wizard.insert_page(self.builder_widgets.get_object('driver_page'),1)
        wizard.insert_page(self.builder_widgets.get_object('up_page'),1)
        wizard.insert_page(self.builder_widgets.get_object('fid_page'),1)
        wizard.insert_page(self.builder_widgets.get_object('base_page'),1)

        #improve the summary
        self.widgets.get_object('version_hbox').show()

        #builder variable defaults
        self.builder_fid_overlay=''
        self.builder_base_image=''
        self.bto_base=False
        self.bto_up=''
        self.add_dell_recovery_deb=''

        self.builder_widgets.connect_signals(self)

    def run(self):
        """Main method for launching the frontend, this needs to be overridden
           because it may be ran from a non-preloaded system"""
        self.widgets.get_object('wizard').show()
        gtk.main()

    def build_page(self,widget,page=None):
        """Processes output that should be done on a builder page"""
        #Do the normal processing first
        GTKFrontend.build_page(self,widget,page)

        wizard = self.widgets.get_object('wizard')
        if page == self.builder_widgets.get_object('base_page'):
            if self.rp:
                self.builder_widgets.get_object('recovery_hbox').set_sensitive(True)
            filter = gtk.FileFilter()
            filter.add_pattern("*.iso")
            self.file_dialog.set_filter(filter)
            wizard.set_page_title(page,_("Choose Base OS Image"))

        elif page == self.builder_widgets.get_object('fid_page'):
            wizard.set_page_title(page,_("Choose FID Overlay"))
            self.builder_widgets.get_object('install_git_button').hide()
            self.builder_widgets.get_object('add_dell_recovery_button').hide()

            for operating_system in git_trees:
                if operating_system == self.distributor:
                    self.builder_widgets.get_object('git_url').set_text(git_trees[operating_system])
            self.fid_toggled(None)

        elif page == self.builder_widgets.get_object('up_page'):
            wizard.set_page_title(page,_("Choose Utility Partition"))
            if self.up:
                self.builder_widgets.get_object('utility_hbox').set_sensitive(True)
            filter = gtk.FileFilter()
            for file in up_filenames:
                pattern = file.split('.')[1]
                filter.add_pattern("*.%s" % pattern)

            self.file_dialog.set_filter(filter)
            self.up_toggled(None)

        elif page == self.builder_widgets.get_object('driver_page'):
            wizard.set_page_title(page,_("Choose Driver Packages"))
            self.file_dialog.set_action(gtk.FILE_CHOOSER_ACTION_OPEN)
            filter = gtk.FileFilter()
            filter.add_pattern("*.tgz")
            filter.add_pattern("*.tar.gz")
            filter.add_pattern("*.deb")
            filter.add_pattern("*.pdf")
            filter.add_pattern("*.py")
            filter.add_pattern("*.sh")

            self.file_dialog.set_filter(filter)
            wizard.set_page_complete(page,True)

        elif page == self.builder_widgets.get_object('application_page'):
            wizard.set_page_title(page,_("Choose Application Packages"))
            self.file_dialog.set_action(gtk.FILE_CHOOSER_ACTION_OPEN)
            filter = gtk.FileFilter()
            filter.add_pattern("*.tgz")
            filter.add_pattern("*.tar.gz")
            filter.add_pattern("*.zip")

            self.file_dialog.set_filter(filter)
            self.calculate_srvs(None, -1, "check")

        elif page == self.widgets.get_object('conf_page') or \
             widget == self.widgets.get_object('version'):

            if page:
                wizard.set_page_title(page,_("Builder Summary"))
            output_text = "<b>" + _("Base Image Distributor") + "</b>: " + self.distributor + '\n'
            output_text+= "<b>" + _("Base Image Release") + "</b>: " + self.release + '\n'
            if self.bto_base:
                output_text+= "<b>" + _("BTO Base Image") + "</b>: " + self.builder_base_image + '\n'
            else:
                output_text+= "<b>" + _("Base Image") + "</b>: " + self.builder_base_image + '\n'
            if self.builder_fid_overlay:
                output_text+= "<b>" + _("FID Overlay") + "</b>: " + self.builder_fid_overlay + '\n'

            if self.bto_up:
                output_text+="<b>" + _("Utility Partition: ") + '</b>' + self.bto_up + '\n'

            liststores = {'application_liststore' : _("Application"),
                          'driver_liststore' : _("Driver"),
                         } 
            for type in liststores:
                model = self.builder_widgets.get_object(type)
                iterator = model.get_iter_first()
                if iterator is not None:
                    output_text += "<b>%s %s</b>:\n" % (liststores[type], _("Packages"))
                while iterator is not None:
                    output_text+= "\t" + model.get_value(iterator,0) + '\n'
                    iterator = model.iter_next(iterator)

            if self.add_dell_recovery_deb:
                output_text+="<b>" + _("Inject Dell Recovery Package") + "</b>: " + self.add_dell_recovery_deb + '\n'

            output_text+= self.widgets.get_object('conf_text').get_label()

            self.widgets.get_object('conf_text').set_markup(output_text)

    def wizard_complete(self, widget):
        """Finished answering wizard questions, and can continue process"""
        #update gui
        self.widgets.get_object('action').set_text(_('Assembling Image Components'))

        #build driver list
        driver_fish_list = []
        model = self.builder_widgets.get_object('driver_liststore')
        iterator = model.get_iter_first()
        while iterator is not None:
            driver_fish_list.append(model.get_value(iterator,0))
            iterator = model.iter_next(iterator)

        #build application list
        application_fish_list = {}
        model = self.builder_widgets.get_object('application_liststore')
        iterator = model.get_iter_first()
        while iterator is not None:
            path = model.get_value(iterator,0)
            srv = model.get_value(iterator,1)
            application_fish_list[path] = srv
            iterator = model.iter_next(iterator)
            
        function='assemble_image'
        args = (self.builder_base_image,
                self.builder_fid_overlay,
                driver_fish_list,
                application_fish_list,
                self.add_dell_recovery_deb,
                'create_' + self.distributor,
                self.bto_up)

        GTKFrontend.wizard_complete(self,widget,function, args)

    def run_file_dialog(self):
        """Browses all files under a particular filter"""
        response = self.file_dialog.run()
        self.file_dialog.hide()
        if response == gtk.RESPONSE_OK:
            return self.file_dialog.get_filename()
        else:
            return None

    def up_toggled(self,widget):
        """Called when the radio button for the Builder utility partition page is changed"""
        up_browse_button=self.builder_widgets.get_object('up_browse_button')
        up_page = self.builder_widgets.get_object('up_page')
        wizard = self.widgets.get_object('wizard')

        if self.builder_widgets.get_object('up_files_radio').get_active():
            self.builder_widgets.get_object('up_details_label').set_markup("")
            self.file_dialog.set_action(gtk.FILE_CHOOSER_ACTION_OPEN)
            up_browse_button.set_sensitive(True)
            wizard.set_page_complete(up_page,False)
        else:
            if self.builder_widgets.get_object('up_partition_radio').get_active():
                self.bto_up = self.up
            else:
                self.bto_up = ''
            wizard.set_page_complete(up_page,True)
            up_browse_button.set_sensitive(False)
            self.up_file_chooser_picked()

    def up_file_chooser_picked(self,widget=None):
        """Called when a file is selected on the up page"""

        up_page = self.builder_widgets.get_object('up_page')
        wizard = self.widgets.get_object('wizard')

        if widget == self.builder_widgets.get_object('up_browse_button'):
            ret=self.run_file_dialog()
            if ret is not None:
                self.bto_up = ret
                wizard.set_page_complete(up_page,True)

        if self.bto_up:
            call = subprocess.Popen(['file', self.bto_up], stdout=subprocess.PIPE)
            output_text = "<b>" + _("Utility Partition") + "</b>:\n"
            output_text+= call.communicate()[0].replace(', ','\n')
        else:
            output_text = _("No Additional Utility Partition")

        self.builder_widgets.get_object('up_details_label').set_markup(output_text)

    def base_toggled(self,widget):
        """Called when the radio button for the Builder base image page is changed"""
        base_browse_button=self.builder_widgets.get_object('base_browse_button')
        base_page = self.builder_widgets.get_object('base_page')
        wizard = self.widgets.get_object('wizard')
        label = self.builder_widgets.get_object('base_image_details_label')

        label.set_markup("")
        base_browse_button.set_sensitive(True)
        wizard.set_page_complete(base_page,False)

        if self.builder_widgets.get_object('iso_image_radio').get_active():
            self.file_dialog.set_action(gtk.FILE_CHOOSER_ACTION_OPEN)
        elif self.builder_widgets.get_object('directory_radio').get_active():
            self.file_dialog.set_action(gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER)
        else:
            base_browse_button.set_sensitive(False)
            self.base_file_chooser_picked()

    def base_file_chooser_picked(self,widget=None):
        """Called when a file is selected on the base page"""

        base_page = self.builder_widgets.get_object('base_page')
        wizard = self.widgets.get_object('wizard')

        wizard.set_page_complete(base_page,False)

        bto_version=''
        output_text=''
        distributor=''
        release=''
        if widget == self.builder_widgets.get_object('base_browse_button'):
            ret=self.run_file_dialog()
            if ret is not None:
                try:
                    (bto_version, distributor, release, output_text) = self.backend().query_iso_information(ret)
                except Exception, e:
                    self.show_alert(gtk.MESSAGE_ERROR, _("Exception"), str(e),
                                    parent=self.widgets.get_object('progress_dialog'))
                self.bto_base=not not bto_version
                self.builder_base_image=ret
                wizard.set_page_complete(base_page,True)
        else:
            try:
                (bto_version, distributor, release, output_text) = self.backend().query_iso_information(self.rp)

                self.bto_base=not not bto_version
                self.builder_base_image=self.rp
                wizard.set_page_complete(base_page,True)
            except dbus.DBusException, e:
                if e._dbus_error_name == PermissionDeniedByPolicy._dbus_error_name:
                    header = _("Permission Denied")
                else:
                    header = str(e)
                self.show_alert(gtk.MESSAGE_ERROR, header,
                            parent=self.widgets.get_object('progress_dialog'))

        if not bto_version:
            bto_version='X00'

        #set the version string that we fetched from the image
        #or increment it if we started from a BTO base image
        if self.bto_base:
            bto_version=increment_bto_version(bto_version)
        self.widgets.get_object('version').set_text(bto_version)

        if distributor:
            self.distributor=distributor
        if release:
            self.release=release

        #If this is a BTO image, then allow using built in framework
        if output_text and \
           not self.bto_base and \
           self.builder_widgets.get_object('builtin_radio').get_active():
            self.builder_widgets.get_object('git_radio').set_active(True)
        self.builder_widgets.get_object('builtin_hbox').set_sensitive(self.bto_base)

        self.builder_widgets.get_object('base_image_details_label').set_markup(output_text)

    def fid_toggled(self,widget):
        """Called when the radio button for the Builder FID overlay page is changed"""
        wizard = self.widgets.get_object('wizard')
        fid_page = self.builder_widgets.get_object('fid_page')
        git_tree_hbox = self.builder_widgets.get_object('fid_git_tree_hbox')
        label = self.builder_widgets.get_object('fid_overlay_details_label')

        label.set_markup("")
        wizard.set_page_complete(fid_page,False)
        git_tree_hbox.set_sensitive(False)

        if self.builder_widgets.get_object('builtin_radio').get_active():
            wizard.set_page_complete(fid_page,True)
            label.set_markup("<b>Builtin</b>: BTO Image")
            self.builder_fid_overlay=''

        elif self.builder_widgets.get_object('git_radio').get_active():
            git_tree_hbox.set_sensitive(True)
            cwd=os.path.join(os.environ["HOME"],'.config','dell-recovery',self.distributor + '-fid')
            if os.path.exists(cwd) and os.path.exists('/usr/bin/git'):
                self.fid_vte_handler(self.builder_widgets.get_object('git_radio'))

    def fid_fetch_button_clicked(self,widget):
        """Called when the button to test a git tree is clicked"""
        wizard = self.widgets.get_object('wizard')
        fid_page = self.builder_widgets.get_object('fid_page')
        label=self.builder_widgets.get_object('fid_overlay_details_label')

        if not os.path.exists('/usr/bin/git'):
            output_text=_("<b>ERROR</b>: git is not installed")
            if not self.ac:
                try:
                    self.ac = client.AptClient()
                except NameError:
                    pass
            if self.ac:
                self.builder_widgets.get_object('install_git_button').show()
            wizard.set_page_complete(fid_page,False)
        else:
            output_text=''
            if not os.path.exists(os.path.join(os.environ['HOME'],'.config','dell-recovery')):
                os.makedirs(os.path.join(os.environ['HOME'],'.config','dell-recovery'))
            if not os.path.exists(os.path.join(os.environ['HOME'],'.config','dell-recovery',self.distributor + '-fid')):
                command=["git", "clone", self.builder_widgets.get_object('git_url').get_text(),
                         os.path.join(os.environ["HOME"],'.config','dell-recovery',self.distributor + '-fid')]
                cwd=os.path.join(os.environ["HOME"],'.config','dell-recovery')
            else:
                command=["git", "fetch", "--verbose"]
                cwd=os.path.join(os.environ["HOME"],'.config','dell-recovery',self.distributor + '-fid')
            self.widgets.get_object('wizard').set_sensitive(False)
            self.builder_widgets.get_object('builder_vte_window').show()
            self.git_pid = self.vte.fork_command(command=command[0],argv=command,directory=cwd)
        label.set_markup(output_text)

    def fid_fetch_cancel(self, widget):
        """Handle a press to the cancel button of the VTE page"""
        os.kill(self.git_pid, 15)

    def fid_vte_handler(self,widget):
        """Handler for VTE dialog closing"""
        def fill_liststore_from_command(command, filter, liststore_name):
            """Fills up the data in a liststore, only items matching filter"""
            liststore=self.builder_widgets.get_object(liststore_name)
            liststore.clear()
            cwd=os.path.join(os.environ["HOME"],'.config','dell-recovery',self.distributor + '-fid')
            if not os.path.exists(cwd):
                return
            list_command=subprocess.Popen(args=command,cwd=cwd,stdout=subprocess.PIPE)
            output=list_command.communicate()[0].split('\n')
            #go through the list once to see if we have A rev tags at all
            use_xrev=self.xrev
            if not use_xrev:
                use_xrev=True
                for item in output:
                    if filter + "_A" in item:
                        use_xrev=False
                        break
            for item in output:
                #Check that we have a valid item
                # AND
                #It doesn't contain HEAD
                # AND
                # [ We are in branch mode
                #   OR
                #   [
                #     It contains our filter
                #     We show X rev builds
                #     It contains an X rev tag
                #   ]
                # ]

                if item and \
                   not "HEAD" in item and \
                   (self.branch or \
                   (filter in item and \
                    (use_xrev or \
                     not filter + "_X" in item))):
                    liststore.append([item])

            #Add this so that we can build w/o a tag only if we are in tag mode w/ dev on
            if use_xrev and not self.branch:
                liststore.append(['origin/master'])

        #reactivate GUI
        self.builder_widgets.get_object('builder_vte_window').hide()
        self.widgets.get_object('wizard').set_sensitive(True)
        self.builder_widgets.get_object('fid_git_tag_hbox').set_sensitive(True)

        #update the tag list in the GUI
        if self.branch:
            command=["git", "branch", "-r"]
        else:
            command=["git","tag","-l"]
        fill_liststore_from_command(command,self.release,'tag_liststore')

    def fid_git_changed(self,widget):
        """If we have selected a tag"""
        wizard = self.widgets.get_object('wizard')
        fid_page = self.builder_widgets.get_object('fid_page')

        active_iter=self.builder_widgets.get_object('git_tags').get_active_iter()
        active_tag=''
        output_text=''
        if active_iter:
            active_tag=self.builder_widgets.get_object('tag_liststore').get_value(
                active_iter,0)

        if active_tag:
            cwd=os.path.join(os.environ["HOME"],'.config','dell-recovery',self.distributor + '-fid')
            #switch checkout branches
            command=["git","checkout",active_tag.strip()]
            subprocess.call(command,cwd=cwd)

            self.builder_fid_overlay=os.path.join(cwd,'framework')

            tag=active_tag.strip().split('_')
            if len(tag) > 1:
                self.widgets.get_object('version').set_text(tag[1])
            else:
                self.widgets.get_object('version').set_text('X00')

            output_text = "<b>GIT Tree</b>, Version: %s" % active_tag

            #if we have a valid tag, check now to make sure that we have dell-recovery
            if self.backend().query_have_dell_recovery(self.builder_base_image,
                                                       self.builder_fid_overlay) or self.add_dell_recovery_deb:
                wizard.set_page_complete(fid_page,True)
            else:
                output_text += "\n<b>%s</b>, %s" % (_("Missing Dell-Recovery"), _("Not present in ISO or GIT tree"))
                wizard.set_page_complete(fid_page,False)
                self.builder_widgets.get_object('add_dell_recovery_button').show()
            
        else:
            wizard.set_page_complete(fid_page,False)
        self.builder_widgets.get_object('fid_overlay_details_label').set_markup(output_text)

    def driver_action(self,widget):
        """Called when the add or remove buttons are pressed on the driver action page"""
        add_button = self.builder_widgets.get_object('driver_add')
        remove_button = self.builder_widgets.get_object('driver_remove')
        treeview = self.builder_widgets.get_object('driver_treeview')
        model = treeview.get_model()
        if widget == add_button:
            ret=self.run_file_dialog()
            if ret is not None:
                #test that we don't have a file named identically
                if self.test_liststore_for_existing(model,ret):
                    return
                model.append([ret])
        elif widget == remove_button:
            row = treeview.get_selection().get_selected_rows()[1]
            if len(row) > 0:
                model.remove(model.get_iter(row[0]))

    def test_liststore_for_existing(self, model, test):
        """Tests the first column of a list store for the same content"""
        iterator = model.get_iter_first()
        while iterator is not None:
            iteration_text = model.get_value(iterator,0)
            if iteration_text == test:
                return True
            iterator = model.iter_next(iterator)
        return False

    def application_action(self,widget):
        def run_srv_dialog():
            """Runs the SRV dialog"""
            srv_dialog = self.builder_widgets.get_object('srv_dialog')
            srv_entry = self.builder_widgets.get_object('srv_entry')
            wizard = self.widgets.get_object('wizard')
            srv_entry.set_text('')
            wizard.set_sensitive(False)
            srv_dialog.run()
            wizard.set_sensitive(True)
            srv_dialog.hide()
            srv = srv_entry.get_text().lower()
            #double check that it's not a duplicate
            if self.calculate_srvs(None, -1, srv):
                return srv
            return ""

        """Called when the add or remove buttons are pressed on the driver action page"""
        add_button = self.builder_widgets.get_object('application_add')
        remove_button = self.builder_widgets.get_object('application_remove')
        treeview = self.builder_widgets.get_object('application_treeview')

        model = treeview.get_model()
        if widget == add_button:
            file_ret = self.run_file_dialog()
            if file_ret is not None:
                #test that we don't have a file named identically
                if self.test_liststore_for_existing(model,file_ret):
                    return
                #query SRVs
                srv = run_srv_dialog()
                #append for reals
                model.append([file_ret,srv])
        elif widget == remove_button:
            row = treeview.get_selection().get_selected_rows()[1]
            if len(row) > 0:
                model.remove(model.get_iter(row[0]))
            self.calculate_srvs(None,-1, "check")

    def calculate_srvs(self, widget, path, text):
        """Verifies that no empty SRVs were defined"""
        wizard = self.widgets.get_object('wizard')
        page = self.builder_widgets.get_object('application_page')
        model = self.builder_widgets.get_object('application_liststore')
        warning = self.builder_widgets.get_object('srv_warning_label')

        #ONLY ever work from lowercase
        text = text.lower()

        #if we are adding text, check all SRVs in the treeview
        # * for duplicates
        # * for having content
        if text:
            proceed = True
            iterator = model.get_iter_first()
            while iterator is not None:
                if str(model.get_path(iterator)[0]) != path:
                    iteration_text = model.get_value(iterator,1)
                    if not iteration_text:
                        proceed = False
                        break
                    if text == iteration_text:
                        proceed = False
                        text = ''
                        break
                iterator = model.iter_next(iterator)
        else:
            proceed = False

        #if we were editing the treeview (not the popup)
        #then add it to the list store
        if path >= 0:
            iterator = model.get_iter(path)
            model.set(iterator, 1, text)

        #Now that we've checked all SRVs, check showing warning and going forward
        if proceed:
            warning.set_text("")
        else:
            warning.set_text(_("All SRVs must be filled to proceed."))
        wizard.set_page_complete(page, proceed)
        return proceed

    def install_app(self,widget):
        """Launch into an installer for git or dpkg-repack"""
        packages = []
        wizard=self.widgets.get_object('wizard')
        if widget == self.builder_widgets.get_object('install_git_button'):
            packages = ['git-core']
        else:
            packages = ['dpkg-repack']
        try:
            t = self.ac.install_packages(packages,
                                    wait=False,
                                    reply_handler=None,
                                    error_handler=None)
            
            dialog = AptProgressDialog(t, parent=wizard)
            dialog.run()
            super(AptProgressDialog, dialog).run()
        except dbus.exceptions.DBusException, e:
            if e._dbus_error_name == "org.freedesktop.PolicyKit.Error.NotAuthorized":
                header = _("Permission Denied")
            else:
                header = _('DBus Exception')
            self.show_alert(gtk.MESSAGE_ERROR, header, str(e),
                        parent=self.widgets.get_object('wizard'))

        widget.hide()

    def add_dell_recovery_clicked(self, widget):
        """Launches a dialog to add dell-recovery to the image"""
        widget.hide()
        #check if dpkg-repack is available
        if not os.path.exists('/usr/bin/dpkg-repack'):
            if not self.ac:
                try:
                    self.ac = client.AptClient()
                except NameError:
                    pass
            if self.ac:
                self.builder_widgets.get_object('add_dell_recovery_repack_button').show()
            self.builder_widgets.get_object('build_dell_recovery_button').set_sensitive(False)
        else:
            self.builder_widgets.get_object('build_dell_recovery_button').set_sensitive(True)
        self.builder_widgets.get_object('builder_add_dell_recovery_window').show()

    def add_dell_recovery_closed(self, widget):
        ok_button = self.builder_widgets.get_object('builder_add_ok')
        fid_page  = self.builder_widgets.get_object('fid_page')
        wizard = self.widgets.get_object('wizard')
        window = self.builder_widgets.get_object('builder_add_dell_recovery_window')

        if widget == ok_button:
            wizard.set_page_complete(fid_page,True)
        else:
            wizard.set_page_complete(fid_page,False)
            self.add_dell_recovery_deb = ''
        window.hide()
        self.fid_git_changed(None)

    def add_dell_recovery_toggled(self, widget):
        """Toggles the active selection in the add dell-recovery to image page"""
        build_radio = self.builder_widgets.get_object('build_dell_recovery_button')
        browse_radio = self.builder_widgets.get_object('provide_dell_recovery_button')
        browse_button = self.builder_widgets.get_object('provide_dell_recovery_browse_button')
        ok_button = self.builder_widgets.get_object('builder_add_ok')

        if build_radio.get_active():
            ok_button.set_sensitive(True)
            browse_button.set_sensitive(False)
            self.add_dell_recovery_deb = 'dpkg-repack'
        elif browse_radio.get_active():
            ok_button.set_sensitive(False)
            browse_button.set_sensitive(True)
            self.add_dell_recovery_deb = ''

    def provide_dell_recovery_file_chooser_picked(self,widget=None):
        """Called when a file is selected on the add dell-recovery page"""

        ok_button = self.builder_widgets.get_object('builder_add_ok')
        filter = gtk.FileFilter()
        filter.add_pattern("*.deb")
        self.file_dialog.set_filter(filter)
            
        ret=self.run_file_dialog()
        if ret is not None:
            import apt_inst
            import apt_pkg
            control = apt_inst.debExtractControl(open(ret))
            sections = apt_pkg.ParseSection(control)
            if sections["Package"] != 'dell-recovery':
                self.add_dell_recovery_deb = ''
            else:
                self.add_dell_recovery_deb = ret

        if self.add_dell_recovery_deb:
            ok_button.set_sensitive(True)
