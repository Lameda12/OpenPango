"""support_writer: picks the email template that matches the situation and drafts it via the guarded tool."""
from __future__ import annotations

from ..context import Ctx

TEMPLATE_FOR = {
    "stuck_customs": "stuck_customs",
    "late": "late",
    "wismo": "wismo",
    "refused": "refused",
    "lost": "lost",
    "address_issue": "address_reissue",
    "delivered_dispute": "delivered_dispute",
    "not_picked_up": "not_picked_up",
}


def run(ctx: Ctx, view: dict, situation: str, extras: dict, ticket_id: int | None = None) -> dict:
    ctx = ctx.as_actor("support_writer")
    return ctx.tool("draft_customer_email", order_id=view["order"]["id"],
                    template=TEMPLATE_FOR.get(situation, situation), extras=extras, ticket_id=ticket_id)
