from .cog import GachaCog


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
