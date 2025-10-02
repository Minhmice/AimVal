class AntiRecoilState:
    """Holds timing info for anti-recoil pulses."""

    def __init__(self):
        self.last_pull_ms = 0


def anti_recoil_tick(
    enabled: bool,
    is_triggering: bool,
    now_ms: int,
    held_ms: int,
    cfg_ar,
    state: AntiRecoilState,
    send_input,
):
    """Apply anti-recoil micro-movements based on configuration and state.

    - Optional gate to require trigger held
    - Minimum ADS hold time before activating
    - Enforced fire rate between pulses
    - Optional random jitter per-axis
    - Scaling with ADS multiplier
    """
    if not cfg_ar.get("enabled", False) or not enabled:
        return
    if cfg_ar.get("only_when_triggering", True) and not is_triggering:
        return
    if held_ms < int(cfg_ar.get("hold_time_ms", 0)):
        return
    if now_ms - state.last_pull_ms < int(cfg_ar.get("fire_rate_ms", 100)):
        return

    dx = int(cfg_ar.get("x_recoil", 0))
    dy = int(cfg_ar.get("y_recoil", 0))

    rj = cfg_ar.get("random_jitter_px", {"x": 0, "y": 0})
    if rj.get("x", 0) or rj.get("y", 0):
        import random
        dx += random.randint(-int(rj.get("x", 0)), int(rj.get("x", 0)))
        dy += random.randint(-int(rj.get("y", 0)), int(rj.get("y", 0)))

    scale_ads = float(cfg_ar.get("scale_with_ads", 1.0))
    dx = int(dx * scale_ads)
    dy = int(dy * scale_ads)

    # Prefer smooth movement if the controller supports it
    try:
        if hasattr(send_input, "move_smooth"):
            send_input.move_smooth(dx, dy, segments=max(1, int(cfg_ar.get("smooth_segments", 2))), ctrl_scale=float(cfg_ar.get("smooth_ctrl_scale", 0.25)))
        else:
            send_input.move(dx, dy)
    except Exception:
        send_input.move(dx, dy)
    state.last_pull_ms = now_ms


