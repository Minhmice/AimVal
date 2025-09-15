@echo off
setlocal
REM Short wrapper to run the tracker quietly
python -m aimval_tracker --overlay --scale 0.8 --log-level warn %*

