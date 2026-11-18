"""Turn a batted ball + verdict into post text and image alt text."""
from __future__ import annotations

from .judge import BattedBall, Verdict

POST_LIMIT = 280


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _feet(x: float) -> str:
    n = max(1, round(abs(x)))
    return f"{n} ft"


def verdict_line(v: Verdict) -> str:
    wall = f"the {v.wall_ft:.0f}-ft wall in {v.zone}"
    if not v.reaches_wall:
        return f"❌ Not a dong at Progressive Field. Lands {_feet(v.short_by_ft)} short of {wall}."
    if v.too_close:
        side = "over" if v.is_dong else "under"
        return (f"🤏 Too close to call at Progressive Field. About {_feet(v.margin_ft)} "
                f"{side} the top of {wall}.")
    if v.is_dong:
        return f"✅ DONG at Progressive Field. Clears {wall} by {_feet(v.margin_ft)}."
    return f"❌ Not a dong at Progressive Field. {_feet(v.margin_ft)} too low for {wall}."


def result_line(ball: BattedBall, v: Verdict) -> str:
    if ball.was_home_run:
        return f"{ball.event} 💣"
    if v.is_dong and not v.too_close:
        return f"{ball.event} 💢"
    return ball.event


def weighted_length(text: str) -> int:
    """Approximate X's character count: most emoji and CJK count double."""
    total = 0
    for ch in text:
        cp = ord(ch)
        single = (cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F
                  or 0x2032 <= cp <= 0x2037)
        total += 1 if single else 2
    return total


def compose(ball: BattedBall, v: Verdict, hashtag: str = "#GuardsBall") -> str:
    half = "🔺" if ball.is_top else "🔻"
    header = [f"{ball.batter} vs {ball.pitcher}"]
    if hashtag:
        header.append(hashtag)
    blocks = [
        "\n".join(header),
        result_line(ball, v),
        "\n".join([
            f"Exit velo: {ball.exit_velo:.1f} mph",
            f"Launch angle: {ball.launch_angle:.0f} deg",
            f"Proj. distance: {ball.distance:.0f} ft",
        ]),
        verdict_line(v),
        f"{ball.away_abbr} ({ball.away_score}) @ {ball.home_abbr} ({ball.home_score})\n"
        f"{half} {ordinal(ball.inning)}",
    ]
    text = "\n\n".join(blocks)
    if weighted_length(text) > POST_LIMIT and hashtag:   # very long names: drop the hashtag
        blocks[0] = header[0]
        text = "\n\n".join(blocks)
    if weighted_length(text) > POST_LIMIT:               # still long: drop the pitcher
        blocks[0] = ball.batter
        text = "\n\n".join(blocks)
    return text


def alt_text(ball: BattedBall, v: Verdict) -> str:
    side = "left of" if v.spray_angle < 0 else "right of"
    outcome = "would be a home run" if v.is_dong else "would not be a home run"
    if v.too_close:
        outcome = "is too close to call"
    return (
        f"Overhead diagram of Progressive Field with the path of {ball.batter}'s "
        f"{ball.event.lower()} drawn from home plate to {v.zone}, {abs(v.spray_angle):.0f} degrees "
        f"{side} dead center. It left the bat at {ball.exit_velo:.1f} mph and {ball.launch_angle:.0f} "
        f"degrees with a projected distance of {ball.distance:.0f} feet. The wall there is "
        f"{v.fence_ft:.0f} feet away and {v.wall_ft:.0f} feet tall. A side view below shows the "
        f"ball's height as it reaches the wall. Verdict: it {outcome} at Progressive Field."
    )
