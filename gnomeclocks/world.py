# Copyright(c) 2011-2012 Collabora, Ltd.
#
# Gnome Clocks is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or(at your
# option) any later version.
#
# Gnome Clocks is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with Gnome Clocks; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
# Author: Seif Lotfy <seif.lotfy@collabora.co.uk>

import os
import errno
import time
from datetime import datetime, date, timedelta
import json
from gi.repository import GLib, GObject, Gio, Gtk, GdkPixbuf
from gi.repository import GWeather
from clocks import Clock
from utils import Dirs, SystemSettings
from widgets import DigitalClockDrawing, SelectableIconView, ContentView


# keep the GWeather world around as a singletom, otherwise
# if is garbage collected get_city_name etc fail.
gweather_world = GWeather.Location.new_world(True)


class WorldClockStorage():
    def __init__(self):
        self.filename = os.path.join(Dirs.get_user_data_dir(), "clocks.json")

    def save(self, clocks):
        location_codes = [c.location.get_code() for c in clocks]
        f = open(self.filename, "wb")
        json.dump(location_codes, f)
        f.close()

    def load(self):
        clocks = []
        try:
            f = open(self.filename, "rb")
            location_codes = json.load(f)
            f.close()
            for l in location_codes:
                location = GWeather.Location.find_by_station_code(gweather_world, l)
                if location:
                    clock = DigitalClock(location)
                    clocks.append(clock)
        except IOError as e:
            if e.errno == errno.ENOENT:
                # File does not exist yet, that's ok
                pass

        return clocks


class NewWorldClockDialog(Gtk.Dialog):
    def __init__(self, parent):
        Gtk.Dialog.__init__(self, _("Add a New World Clock"), parent)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_size_request(400, -1)
        self.set_border_width(3)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        area = self.get_content_area()
        area.pack_start(box, True, True, 0)

        label = Gtk.Label(_("Search for a city:"))
        label.set_alignment(0.0, 0.5)

        self.entry = GWeather.LocationEntry.new(gweather_world)
        self.find_gicon = Gio.ThemedIcon.new_with_default_fallbacks(
            'edit-find-symbolic')
        self.clear_gicon = Gio.ThemedIcon.new_with_default_fallbacks(
            'edit-clear-symbolic')
        self.entry.set_icon_from_gicon(
            Gtk.EntryIconPosition.SECONDARY, self.find_gicon)
        self.entry.set_activates_default(True)

        self.add_buttons(Gtk.STOCK_CANCEL, 0, Gtk.STOCK_ADD, 1)
        self.set_default_response(1)
        self.set_response_sensitive(1, False)

        box.pack_start(label, False, False, 6)
        box.pack_start(self.entry, False, False, 3)
        box.set_border_width(5)

        self.entry.connect("activate", self._set_city)
        self.entry.connect("changed", self._set_city)
        self.entry.connect("icon-release", self._icon_released)
        self.show_all()

    def get_location(self):
        return self.entry.get_location()

    def _set_city(self, widget):
        location = self.entry.get_location()
        if self.entry.get_text() == '':
            self.entry.set_icon_from_gicon(
                Gtk.EntryIconPosition.SECONDARY, self.find_gicon)
        else:
            self.entry.set_icon_from_gicon(
                Gtk.EntryIconPosition.SECONDARY, self.clear_gicon)
        if location:
            self.set_response_sensitive(1, True)
        else:
            self.set_response_sensitive(1, False)

    def _icon_released(self, icon_pos, event, data):
        if self.entry.get_icon_gicon(
            Gtk.EntryIconPosition.SECONDARY) == self.clear_gicon:
            self.entry.set_text('')
            self.entry.set_icon_from_gicon(
              Gtk.EntryIconPosition.SECONDARY, self.find_gicon)
            self.set_response_sensitive(1, False)


class DigitalClock():
    def __init__(self, location):
        self.location = location
        self._last_sunrise = datetime.strptime("197007:00", "%Y%H:%M")
        self.sunrise = self._last_sunrise
        self._last_sunset = datetime.strptime("197019:00", "%Y%H:%M")
        self.sunset = self._last_sunset
        self.get_sunrise_sunset()

        self.path = None
        self.list_store = None

        weather_timezone = self.location.get_timezone()
        timezone = GLib.TimeZone.new(weather_timezone.get_tzid())
        i = timezone.find_interval(GLib.TimeType.UNIVERSAL, time.time())
        location_offset = timezone.get_offset(i)

        timezone = GLib.TimeZone.new_local()
        i = timezone.find_interval(GLib.TimeType.UNIVERSAL, time.time())
        here_offset = timezone.get_offset(i)

        self.offset = location_offset - here_offset

        self._last_time = None
        self.drawing = DigitalClockDrawing()
        self.standalone = None
        self.update()

    def get_location_time(self, secs=None):
        if not secs:
            secs = time.time()
        t = datetime.fromtimestamp(secs + self.offset)
        return t

    def update(self, secs=None):
        clock_format = SystemSettings.get_clock_format()
        location_time = self.get_location_time(secs)
        if clock_format == '12h':
            t = location_time.strftime("%I:%M %p")
        else:
            t = location_time.strftime("%H:%M")
        if t.startswith("0"):
            t = t[1:]
        if not t == self._last_time \
                or not self.sunrise == self._last_sunrise \
                or not self.sunset == self._last_sunset:
            is_light = self.get_is_light(location_time)
            if is_light:
                img = os.path.join(Dirs.get_image_dir(), "cities", "day.png")
            else:
                img = os.path.join(Dirs.get_image_dir(), "cities", "night.png")
            day = self.get_day(secs)
            if day == "Today":
                self.drawing.render(t, img, is_light)
            else:
                self.drawing.render(t, img, is_light, day)
            if self.path and self.list_store:
                self.list_store[self.path][1] = self.drawing.pixbuf
            if self.standalone:
                self.standalone.update(img, t, self.sunrise, self.sunset)

        self._last_time = t

    def get_sunrise_sunset(self):
        self.weather = GWeather.Info(location=self.location, world=gweather_world)
        self.weather.connect('updated', self._on_weather_updated)
        self.weather.update()

    def _on_weather_updated(self, weather):
        # returned as the time here
        ok, sunrise = weather.get_value_sunrise()
        ok, sunset = weather.get_value_sunset()
        self._last_sunrise = self.sunrise
        self._last_sunset = self.sunset
        self.sunrise = self.get_location_time(sunrise)
        self.sunset = self.get_location_time(sunset)
        self.update()

    def get_pixbuf(self):
        return self.drawing.pixbuf

    def get_standalone_widget(self):
        if not self.standalone:
            self.standalone = StandaloneClock(self.location, self.sunrise, self.sunset)
        self.update()
        return self.standalone

    def get_day(self, secs=None):
        clock_time = self.get_location_time(secs)

        clock_time_day = clock_time.date()
        local_today = date.today()

        date_offset = (clock_time_day - local_today).days
        if date_offset == 0:
            return "Today"
        elif date_offset < 0:
            if date_offset == -1:
                return "Yesterday"
            else:
                return "%d days ago" % abs(date_offset)
        elif date_offset > 0:
            if date_offset == 1:
                return "Tomorrow"
            else:
                return "%d days from now" % abs(date_offset)
        else:
            return clock_time_day.strftime("%A")

    def get_is_light(self, current):
        return self.sunrise.time() <= current.time() <= self.sunset.time()

    def set_path(self, list_store, path):
        self.path = path
        self.list_store = list_store


class World(Clock):
    def __init__(self):
        # Translators: "New" refers to a world clock
        Clock.__init__(self, _("World"), _("New"), True)

        self.liststore = Gtk.ListStore(bool,
                                       GdkPixbuf.Pixbuf,
                                       str,
                                       GObject.TYPE_PYOBJECT)

        self.iconview = SelectableIconView(self.liststore, 0, 1, 2)

        contentview = ContentView(self.iconview,
                "document-open-recent-symbolic",
                 _("Select <b>New</b> to add a world clock"))
        
        self.timeview = TimeAdjustingView(contentview)
        self.add(self.timeview)

        self.timeview.connect("time-changed", self._on_timeview_time_changed)
        self.iconview.connect("item-activated", self._on_item_activated)
        self.iconview.connect("selection-changed", self._on_selection_changed)

        self.storage = WorldClockStorage()
        self.clocks = []
        self.load_clocks()
        self.show_all()

        self.timeout_id = GObject.timeout_add(1000, self._update_clocks)

    def _update_clocks(self):
        time_override = self.timeview.get_seconds()
        for c in self.clocks:
            c.update(time_override)
        return True

    def _on_timeview_time_changed(self, timeview):
        self._update_clocks()

    def _on_item_activated(self, iconview, path):
        d = self.liststore[path][3]
        self.emit("show-standalone", d)

    def _on_selection_changed(self, iconview):
        self.emit("selection-changed")

    def set_selection_mode(self, active):
        self.iconview.set_selection_mode(active)

    @GObject.Property(type=bool, default=False)
    def can_select(self):
        return len(self.liststore) != 0

    def get_selection(self):
        return self.iconview.get_selection()

    def delete_selected(self):
        selection = self.get_selection()
        items = []
        for treepath in selection:
            items.append(self.liststore[treepath][3])
        self.delete_clocks(items)

    def load_clocks(self):
        self.clocks = self.storage.load()
        for clock in self.clocks:
            self.add_clock_widget(clock)

    def add_clock(self, location):
        for c in self.clocks:
            if c.location.get_code() == location.get_code():
                # duplicate
                return
        clock = DigitalClock(location)
        self.clocks.append(clock)
        self.storage.save(self.clocks)
        self.add_clock_widget(clock)
        self.show_all()

    def add_clock_widget(self, clock):
        name = clock.location.get_city_name()
        label = GLib.markup_escape_text(name)
        view_iter = self.liststore.append([False,
                                           clock.get_pixbuf(),
                                           "<b>%s</b>" % label,
                                           clock])
        path = self.liststore.get_path(view_iter)
        clock.set_path(self.liststore, path)
        self.notify("can-select")

    def delete_clocks(self, clocks):
        for c in clocks:
            self.clocks.remove(c)
        self.storage.save(self.clocks)
        self.iconview.unselect_all()
        self.liststore.clear()
        self.load_clocks()
        self.notify("can-select")

    def open_new_dialog(self):
        window = NewWorldClockDialog(self.get_toplevel())
        window.connect("response", self._on_dialog_response)
        window.show_all()

    def _on_dialog_response(self, dialog, response):
        if response == 1:
            l = dialog.get_location()
            self.add_clock(l)
        dialog.destroy()


class TimeAdjustingView(Gtk.Box):
    __gsignals__ = {
    'time-changed': (GObject.SignalFlags.RUN_LAST,
                          None,
                          ())
    }
    
    def __init__(self, content):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.content = content

        self.timebar = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 24*60*60, 60)
        self.timebar.pack_start(self.slider, True, True, 12)

        self.pack_start(self.timebar, False, False, 0)
        self.pack_end(content, True, True, 0)

        self.slider.connect("value-changed", self._on_slider_value_changed)
        self.slider.connect("format-value", self._on_slider_format_value)

    def get_time(self):
        offset_seconds = self.slider.get_value()
        value_time = datetime.now() + timedelta(seconds=offset_seconds)
        return value_time

    def get_seconds(self):
        offset_seconds = self.slider.get_value()
        value_seconds = time.time() + offset_seconds
        return value_seconds

    def _on_slider_value_changed(self, scale):
        self.emit("time-changed")

    def _on_slider_format_value(self, scale, value):
        #TODO: Sync this code with DigitalClock (and pull code into utils.py where necessary)
        clock_format = SystemSettings.get_clock_format()

        value_time = self.get_time()
        tomorrow = date.today() + timedelta(days=1)

        if clock_format == "12h":
            if value_time.date() >= tomorrow:
                time_str = value_time.strftime("%I:%M %p tomorrow")
            else:
                time_str = value_time.strftime("%I:%M %p")
        else:
            if value_time.date() >= tomorrow:
                time_str = value_time.strftime("%H:%M tomorrow")
            else:
                time_str = value_time.strftime("%H:%M")
        if time_str.startswith("0"):
            time_str = time_str[1:]

        return time_str


class StandaloneClock(Gtk.EventBox):
    def __init__(self, location, sunrise, sunset):
        Gtk.EventBox.__init__(self)
        self.get_style_context().add_class('view')
        self.get_style_context().add_class('content-view')
        self.location = location
        self.can_edit = False
        self.time_label = Gtk.Label()
        self.sunrise = sunrise
        self.sunset = sunset

        self.clock_format = None

        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(self.vbox)

        time_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.time_label.set_alignment(0.0, 0.5)
        time_box.pack_start(self.time_label, True, True, 0)

        self.hbox = hbox = Gtk.Box()
        self.hbox.set_homogeneous(False)

        self.hbox.pack_start(Gtk.Label(), True, True, 0)
        self.hbox.pack_start(time_box, False, False, 0)
        self.hbox.pack_start(Gtk.Label(), True, True, 0)

        self.vbox.pack_start(Gtk.Label(), True, True, 25)
        self.vbox.pack_start(hbox, False, False, 0)
        self.vbox.pack_start(Gtk.Label(), True, True, 0)

        sunrise_label = Gtk.Label()
        sunrise_label.set_markup(
            "<span size ='large' color='dimgray'>%s</span>" % (_("Sunrise")))
        sunrise_label.set_alignment(1.0, 0.5)
        self.sunrise_time_label = Gtk.Label()
        self.sunrise_time_label.set_alignment(0.0, 0.5)
        sunrise_hbox = Gtk.Box(True, 9)
        sunrise_hbox.pack_start(sunrise_label, False, False, 0)
        sunrise_hbox.pack_start(self.sunrise_time_label, False, False, 0)

        sunset_label = Gtk.Label()
        sunset_label.set_markup(
            "<span size ='large' color='dimgray'>%s</span>" % (_("Sunset")))
        sunset_label.set_alignment(1.0, 0.5)
        self.sunset_time_label = Gtk.Label()
        self.sunset_time_label.set_alignment(0.0, 0.5)
        sunset_hbox = Gtk.Box(True, 9)
        sunset_hbox.pack_start(sunset_label, False, False, 0)
        sunset_hbox.pack_start(self.sunset_time_label, False, False, 0)

        sunbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sunbox.set_homogeneous(True)
        sunbox.set_spacing(3)
        sunbox.pack_start(sunrise_hbox, False, False, 3)
        sunbox.pack_start(sunset_hbox, False, False, 3)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hbox.pack_start(Gtk.Label(), True, True, 0)
        hbox.pack_start(sunbox, False, False, 0)
        hbox.pack_start(Gtk.Label(), True, True, 0)
        self.vbox.pack_end(hbox, False, False, 30)

        self.show_all()

    def get_name(self):
        return GLib.markup_escape_text(self.location.get_city_name())

    def update(self, img, text, sunrise, sunset):
        size = 72000  # FIXME: (self.get_allocation().height / 300) * 72000
        self.time_label.set_markup(
            "<span size='%i' color='dimgray'><b>%s</b></span>" % (size, text))
        clock_format = SystemSettings.get_clock_format()
        if clock_format != self.clock_format or \
                sunrise != self.sunrise or sunset != self.sunset:
            self.sunrise = sunrise
            self.sunset = sunset
            if clock_format == "12h":
                sunrise_str = sunrise.strftime("%I:%M %p")
                sunset_str = sunset.strftime("%I:%M %p")
            else:
                sunrise_str = sunrise.strftime("%H:%M")
                sunset_str = sunset.strftime("%H:%M")
            if sunrise_str.startswith("0"):
                sunrise_str = sunrise_str[1:]
            if sunset_str.startswith("0"):
                sunset_str = sunset_str[1:]
            self.sunrise_time_label.set_markup(
                "<span size ='large'>%s</span>" % sunrise_str)
            self.sunset_time_label.set_markup(
                "<span size ='large'>%s</span>" % sunset_str)
        self.clock_format = clock_format
