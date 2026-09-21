#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Jun 25 10:44:24 2017

@author: wroscoe
"""

import time
import signal
import numpy as np
import logging
from threading import Thread
from .memory import Memory
from prettytable import PrettyTable
import traceback

logger = logging.getLogger(__name__)


def _sigterm_as_keyboard_interrupt(signum, frame):
    """把 SIGTERM 转成 KeyboardInterrupt，让 Vehicle 走正常收尾路径。

    默认的 SIGTERM 会立即终止解释器，``Vehicle.start`` 的 ``finally`` 不会
    执行，于是 ``stop()`` 末尾的 part 耗时表（Part Profile Summary）也打不
    出来。``donkey drive`` 停止车端子进程用的正是 SIGTERM，因此这里接管它，
    使其等价于终端 Ctrl+C，保证耗时表仍能输出，便于做系统状态校验。
    """
    raise KeyboardInterrupt


class PartProfiler:
    def __init__(self):
        self.records = {}

    def profile_part(self, p):
        self.records[p] = { "times" : [] }

    def on_part_start(self, p):
        self.records[p]['times'].append(time.time())

    def on_part_finished(self, p):
        now = time.time()
        prev = self.records[p]['times'][-1]
        delta = now - prev
        thresh = 0.000001
        if delta < thresh or delta > 100000.0:
            delta = thresh
        self.records[p]['times'][-1] = delta

    def report(self):
        logger.info("Part Profile Summary: (times in ms)")
        pt = PrettyTable()
        field_names = ["part", "max", "min", "avg"]
        pctile = [50, 90, 99, 99.9]
        pt.field_names = field_names + [str(p) + '%' for p in pctile]
        for p, val in self.records.items():
            # remove first and last entry because you there could be one-off
            # time spent in initialisations, and the latest diff could be
            # incomplete because of user keyboard interrupt
            arr = val['times'][1:-1]
            if len(arr) == 0:
                continue
            row = [p.__class__.__name__,
                   "%.2f" % (max(arr) * 1000),
                   "%.2f" % (min(arr) * 1000),
                   "%.2f" % (sum(arr) / len(arr) * 1000)]
            row += ["%.2f" % (np.percentile(arr, p) * 1000) for p in pctile]
            pt.add_row(row)
        logger.info('\n' + str(pt))


class Vehicle:
    def __init__(self, mem=None):

        if not mem:
            mem = Memory()
        self.mem = mem
        self.parts = []
        self.on = True
        self.threads = []
        self.profiler = PartProfiler()

    def add(self, part, inputs=[], outputs=[],
            threaded=False, run_condition=None):
        """
        Method to add a part to the vehicle drive loop.

        Parameters
        ----------
            part: class
                donkey vehicle part has run() attribute
            inputs : list
                Channel names to get from memory.
            outputs : list
                Channel names to save to memory.
            threaded : boolean
                If a part should be run in a separate thread.
            run_condition : str
                If a part should be run or not
        """
        assert type(inputs) is list, "inputs is not a list: %r" % inputs
        assert type(outputs) is list, "outputs is not a list: %r" % outputs
        assert type(threaded) is bool, "threaded is not a boolean: %r" % threaded

        p = part
        logger.info('Adding part {}.'.format(p.__class__.__name__))
        entry = {}
        entry['part'] = p
        entry['inputs'] = inputs
        entry['outputs'] = outputs
        entry['run_condition'] = run_condition

        if threaded:
            t = Thread(target=part.update, args=())
            t.daemon = True
            entry['thread'] = t

        self.parts.append(entry)
        self.profiler.profile_part(part)

    def remove(self, part):
        """
        remove part form list
        """
        self.parts.remove(part)

    def start(self, rate_hz=10, max_loop_count=None, verbose=False):
        """
        Start vehicle's main drive loop.

        This is the main thread of the vehicle. It starts all the new
        threads for the threaded parts then starts an infinite loop
        that runs each part and updates the memory.

        Parameters
        ----------

        rate_hz : int
            The max frequency that the drive loop should run. The actual
            frequency may be less than this if there are many blocking parts.
        max_loop_count : int
            Maximum number of loops the drive loop should execute. This is
            used for testing that all the parts of the vehicle work.
        verbose: bool
            If debug output should be printed into shell
        """

        # 外部链路（donkey drive 等）通过 SIGTERM 停止车进程，默认行为会直接
        # 终止解释器而跳过 finally。这里接管 SIGTERM，使其等价于 Ctrl+C，从而
        # 在退出前执行 stop() 并打印 part 耗时表。非主线程无法安装信号处理器，
        # 此时退化为系统默认行为。
        prev_sigterm = None
        try:
            prev_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _sigterm_as_keyboard_interrupt)
        except (ValueError, OSError):
            prev_sigterm = None

        try:

            self.on = True

            for entry in self.parts:
                if entry.get('thread'):
                    # start the update thread
                    entry.get('thread').start()

            # wait until the parts warm up.
            logger.info('Starting vehicle at {} Hz'.format(rate_hz))

            loop_start_time = time.time()
            loop_count = 0
            while self.on:
                start_time = time.time()
                loop_count += 1

                self.update_parts()

                # stop drive loop if loop_count exceeds max_loopcount
                if max_loop_count and loop_count >= max_loop_count:
                    self.on = False
                else:
                    sleep_time = 1.0 / rate_hz - (time.time() - start_time)
                    if sleep_time > 0.0:
                        time.sleep(sleep_time)
                    else:
                        # print a message when could not maintain loop rate.
                        if verbose:
                            logger.info('WARN::Vehicle: jitter violation in vehicle loop '
                                  'with {0:4.0f}ms'.format(abs(1000 * sleep_time)))

                    if verbose and loop_count % 200 == 0:
                        self.profiler.report()


            loop_total_time = time.time() - loop_start_time
            logger.info(f"Vehicle executed {loop_count} steps in {loop_total_time} seconds.")

            return loop_count, loop_total_time

        except KeyboardInterrupt:
            pass
        except Exception as e:
            traceback.print_exc()
        finally:
            if prev_sigterm is not None:
                try:
                    signal.signal(signal.SIGTERM, prev_sigterm)
                except (ValueError, OSError):
                    pass
            self.stop()

    def update_parts(self):
        '''
        loop over all parts
        '''
        for entry in self.parts:

            run = True
            # check run condition, if it exists
            if entry.get('run_condition'):
                run_condition = entry.get('run_condition')
                run = self.mem.get([run_condition])[0]
            
            if run:
                # get part
                p = entry['part']
                # start timing part run
                self.profiler.on_part_start(p)
                # get inputs from memory
                inputs = self.mem.get(entry['inputs'])
                # run the part
                if entry.get('thread'):
                    outputs = p.run_threaded(*inputs)
                else:
                    outputs = p.run(*inputs)

                # save the output to memory
                if outputs is not None:
                    self.mem.put(entry['outputs'], outputs)
                # finish timing part run
                self.profiler.on_part_finished(p)

    def stop(self):        
        logger.info('Shutting down vehicle and its parts...')
        for entry in self.parts:
            try:
                entry['part'].shutdown()
            except AttributeError:
                # usually from missing shutdown method, which should be optional
                pass
            except Exception as e:
                logger.error(e)

        self.profiler.report()
