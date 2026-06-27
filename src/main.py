import gc

mem_free_startup = gc.mem_free()

import lvgl as lv
import lcd_bus
import ili9341
import xpt2046
from machine import SPI, Pin
import i2c
import machine
import micropython
import task_handler
import time
import math
import asyncio

# ============== Customize settings ============== #
# The following values need to be customized.

# Switch width and height for portrait mode.
_DISPLAY_WIDTH = micropython.const(320)
_DISPLAY_HEIGHT = micropython.const(240)
# Try different values from rotation table, see below.
_DISPLAY_ROT = micropython.const(0x80)
# Set to True if red and blue are switched.
_DISPLAY_BGR = micropython.const(0)
# May have to be set to 0 if both RGB / BGR mode give bad results.
_DISPLAY_RGB565_BYTE_SWAP = micropython.const(1)
# Allow touch calibration. Set to True when display works correctly.
_ALLOW_TOUCH_CAL = micropython.const(1)
# Show marker at current touch coordinates.
_DISPLAY_SHOW_TOUCH_INDICATOR = micropython.const(1)

# ============== Display / Indev initialization ============== #
# no need to change anything below here
_SPI_BUS_HOST = micropython.const(1)
_SPI_BUS_MOSI = micropython.const(13)
_SPI_BUS_MISO = micropython.const(12)
_SPI_BUS_SCK = micropython.const(14)
_INDEV_BUS_HOST = micropython.const(2)
_INDEV_BUS_MOSI = micropython.const(32)
_INDEV_BUS_MISO = micropython.const(39)
_INDEV_BUS_SCK = micropython.const(25)
_INDEV_DEVICE_FREQ = micropython.const(2000000)
_INDEV_DEVICE_CS = micropython.const(33)
_DISPLAY_BUS_FREQ = micropython.const(24000000)
_DISPLAY_BUS_DC = micropython.const(2)
_DISPLAY_BUS_CS = micropython.const(15)
_DISPLAY_BACKLIGHT_PIN = micropython.const(21)

s1 = None
agitate_click_event = asyncio.Event()
stop_click_event = asyncio.Event()

class Stepper:
    def __init__(self,step_pin,dir_pin,en_pin=None,steps_per_rev=200,speed_sps=10,invert_dir=False,timer_id=-1):
        
        if not isinstance(step_pin, machine.Pin):
            step_pin=machine.Pin(step_pin,machine.Pin.OUT)
        if not isinstance(dir_pin, machine.Pin):
            dir_pin=machine.Pin(dir_pin,machine.Pin.OUT)
        if (en_pin != None) and (not isinstance(en_pin, machine.Pin)):
            en_pin=machine.Pin(en_pin,machine.Pin.OUT)
                 
        self.step_value_func = step_pin.value
        self.dir_value_func = dir_pin.value
        self.en_pin = en_pin
        self.invert_dir = invert_dir

        self.timer = machine.Timer(timer_id)
        self.timer_is_running=False
        self.free_run_mode=0
        self.enabled=True
        
        self.target_pos = 0
        self.pos = 0
        self.steps_per_sec = speed_sps
        self.steps_per_rev = steps_per_rev
        
        self.track_target()
        
    def speed(self,sps):
        self.steps_per_sec = sps
        if self.timer_is_running:
            self.track_target()
    
    def speed_rps(self,rps):
        self.speed(rps*self.steps_per_rev)

    def target(self,t):
        self.target_pos = t

    def target_deg(self,deg):
        self.target(self.steps_per_rev*deg/360.0)
    
    def target_rad(self,rad):
        self.target(self.steps_per_rev*rad/(2.0*math.pi))
    
    def get_pos(self):
        return self.pos
    
    def get_pos_deg(self):
        return self.get_pos()*360.0/self.steps_per_rev
    
    def get_pos_rad(self):
        return self.get_pos()*(2.0*math.pi)/self.steps_per_rev
    
    def overwrite_pos(self,p):
        self.pos = 0
    
    def overwrite_pos_deg(self,deg):
        self.overwrite_pos(deg*self.steps_per_rev/360.0)
    
    def overwrite_pos_rad(self,rad):
        self.overwrite_pos(rad*self.steps_per_rev/(2.0*math.pi))

    def step(self,d):
        if d>0:
            if self.enabled:
                self.dir_value_func(1^self.invert_dir)
                self.step_value_func(1)
                self.step_value_func(0)
            self.pos+=1
        elif d<0:
            if self.enabled:
                self.dir_value_func(0^self.invert_dir)
                self.step_value_func(1)
                self.step_value_func(0)
            self.pos-=1

    def _timer_callback(self,t):
        if self.free_run_mode>0:
            self.step(1)
        elif self.free_run_mode<0:
            self.step(-1)
        elif self.target_pos>self.pos:
            self.step(1)
        elif self.target_pos<self.pos:
            self.step(-1)
    
    def free_run(self,d):
        self.free_run_mode=d
        if self.timer_is_running:
            self.timer.deinit()
        if d!=0:
            self.timer.init(freq=self.steps_per_sec,callback=self._timer_callback)
            self.timer_is_running=True
        else:
            self.dir_value_func(0)

    def track_target(self):
        self.free_run_mode=0
        if self.timer_is_running:
            self.timer.deinit()
        self.timer.init(freq=self.steps_per_sec,callback=self._timer_callback)
        self.timer_is_running=True

    def stop(self):
        self.free_run_mode=0
        if self.timer_is_running:
            self.timer.deinit()
        self.timer_is_running=False
        self.dir_value_func(0)

    def enable(self,e):
        if self.en_pin:
            self.en_pin.value(e)
        self.enabled=e
        if not e:
            self.dir_value_func(0)
    
    def is_enabled(self):
        return self.enabled


# Define event callback function.
def agitate():
    global s1
    print("agitate")
    s1.free_run(1)
    time.sleep(10.0)
    s1.free_run(-1)
    time.sleep(10.0)
    s1.free_run(0)

def stop():
    global s1
    print("stop")
    s1.stop()

async def handle_agitate_button_clicks():
    while True:
        await agitate_click_event.wait() # Wait for the click
        
        print("Agitate button was clicked! Doing async work...")
        agitate()
        await asyncio.sleep(1)   # Non-blocking delay
        agitate_click_event.clear()      # Reset the event for the next click
        print("Async agitate task finished.")

async def handle_stop_button_clicks():
    while True:
        await stop_click_event.wait() # Wait for the click
        
        print("Stop button was clicked! Doing async work...")
        stop()
        await asyncio.sleep(1)   # Non-blocking delay
        stop_click_event.clear()      # Reset the event for the next click
        print("Async stop task finished.")

def agitate_button_event_handler(evt):
    print("agitate_button_event_handler")
    agitate_click_event.set()

def stop_button_event_handler(evt):
    print("stop_button_event_handler")
    stop_click_event.set()

async def main():
    task1 = asyncio.create_task(handle_agitate_button_clicks())
    task2 = asyncio.create_task(handle_stop_button_clicks())
    await asyncio.gather(task1, task2)

if __name__ == "__main__":
    
    spi_bus = machine.SPI.Bus(
        host=_SPI_BUS_HOST,
        mosi=_SPI_BUS_MOSI,
        miso=_SPI_BUS_MISO,
        sck=_SPI_BUS_SCK
    )

    indev_bus = machine.SPI.Bus(
        host=_INDEV_BUS_HOST,
        mosi=_INDEV_BUS_MOSI,
        miso=_INDEV_BUS_MISO,
        sck=_INDEV_BUS_SCK
    )

    indev_device = machine.SPI.Device(
        spi_bus=indev_bus,
        freq=_INDEV_DEVICE_FREQ,
        cs=_INDEV_DEVICE_CS
    )

    display_bus = lcd_bus.SPIBus(
        spi_bus=spi_bus,
        freq=_DISPLAY_BUS_FREQ,
        dc=_DISPLAY_BUS_DC,
        cs=_DISPLAY_BUS_CS
    )

    display = ili9341.ILI9341(
        data_bus=display_bus,
        display_width=_DISPLAY_WIDTH,
        display_height=_DISPLAY_HEIGHT,
        backlight_pin=_DISPLAY_BACKLIGHT_PIN,
        backlight_on_state=ili9341.STATE_PWM,
        color_space=lv.COLOR_FORMAT.RGB565,
        color_byte_order=ili9341.BYTE_ORDER_BGR if _DISPLAY_BGR else ili9341.BYTE_ORDER_RGB,
        rgb565_byte_swap=_DISPLAY_RGB565_BYTE_SWAP
    )

    # The rotation table MUST be defined
    display._ORIENTATION_TABLE = (
        _DISPLAY_ROT, # this value sets the rotation
        0x0, # placeholder
        0x0, # placeholder
        0x0 # placeholder
    )

    # lv.DISPLAY_ROTATION._0 uses the first value from the
    # display._ORIENTATION_TABLE to set display rotation
    display.set_rotation(lv.DISPLAY_ROTATION._0)
    display.set_power(True)
    display.init(1)
    display.set_backlight(100)

    indev = xpt2046.XPT2046(device=indev_device)

    # Calibration data is stored in the non-volatile storage (NVS) of the Esp32
    if not indev.is_calibrated:
        indev.calibrate()

    s1 = Stepper(27, 22, steps_per_rev=200, speed_sps=750, timer_id=1)

    # ============== End of display / touch (indev) setup ============== #
    scrn = lv.screen_active()
    scrn.set_style_bg_color(lv.color_white(), lv.PART.MAIN)
    scrn.remove_flag(lv.obj.FLAG.SCROLLABLE)

    agitate_btn = lv.button(scrn)
    agitate_btn.add_flag(lv.obj.FLAG.CLICKABLE)
    agitate_label = lv.label(agitate_btn)
    agitate_label.set_text("Agitate")
    agitate_btn.align(lv.ALIGN.CENTER, -50, 0)

    stop_btn = lv.button(scrn)
    stop_btn.add_flag(lv.obj.FLAG.CLICKABLE)
    stop_label = lv.label(stop_btn)
    stop_label.set_text("Stop")
    stop_btn.align(lv.ALIGN.CENTER, 50, 0)

    # Add the event (triggered when clicked) to the button.
    agitate_btn.add_event_cb(agitate_button_event_handler, lv.EVENT.CLICKED, None)
    stop_btn.add_event_cb(stop_button_event_handler, lv.EVENT.CLICKED, None)

    task_handler.TaskHandler()
    asyncio.run(main())
