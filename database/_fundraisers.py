import time
import asyncpg


class FundraisersMixin:
    async def create_fundraiser(self, guild_id, creator_id, description, goal):
        row = await self._pool.fetchrow(
            "INSERT INTO fundraisers (guild_id, creator_id, description, goal, created_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            guild_id, creator_id, description, goal, int(time.time()),
        )
        return row["id"]

    async def get_fundraiser(self, fundraiser_id):
        return await self._pool.fetchrow("SELECT * FROM fundraisers WHERE id = $1", fundraiser_id)

    async def set_fundraiser_message(self, fundraiser_id, channel_id, message_id):
        await self._pool.execute(
            "UPDATE fundraisers SET channel_id = $1, message_id = $2 WHERE id = $3",
            channel_id, message_id, fundraiser_id,
        )

    async def update_fundraiser_status(self, fundraiser_id, status):
        await self._pool.execute(
            "UPDATE fundraisers SET status = $1 WHERE id = $2", status, fundraiser_id
        )

    async def donate_to_fundraiser(self, fundraiser_id, guild_id, donor_id, amount):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO fundraiser_donations (fundraiser_id, guild_id, donor_id, amount, timestamp) VALUES ($1, $2, $3, $4, $5)",
                    fundraiser_id, guild_id, donor_id, amount, int(time.time()),
                )
                await conn.execute(
                    "UPDATE fundraisers SET raised = raised + $1 WHERE id = $2", amount, fundraiser_id
                )
                row = await conn.fetchrow(
                    "SELECT raised FROM fundraisers WHERE id = $1", fundraiser_id
                )
        return row["raised"]

    async def get_fundraiser_donations(self, fundraiser_id):
        return await self._pool.fetch(
            "SELECT * FROM fundraiser_donations WHERE fundraiser_id = $1", fundraiser_id
        )

    async def add_fundraiser_vote(self, fundraiser_id, voter_id, vote):
        try:
            await self._pool.execute(
                "INSERT INTO fundraiser_votes (fundraiser_id, voter_id, vote) VALUES ($1, $2, $3)",
                fundraiser_id, voter_id, vote,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False

    async def get_fundraiser_votes(self, fundraiser_id):
        return await self._pool.fetch(
            "SELECT * FROM fundraiser_votes WHERE fundraiser_id = $1", fundraiser_id
        )

    async def get_active_fundraisers(self, guild_id):
        return await self._pool.fetch(
            "SELECT * FROM fundraisers WHERE guild_id = $1 AND status IN ('open', 'funded', 'voting') ORDER BY created_at DESC",
            guild_id,
        )

    async def refund_fundraiser(self, fundraiser_id):
        donations = await self.get_fundraiser_donations(fundraiser_id)
        fr = await self.get_fundraiser(fundraiser_id)
        for d in donations:
            await self.add_yuan(fr["guild_id"], d["donor_id"], d["amount"])
        await self.update_fundraiser_status(fundraiser_id, "refunded")
