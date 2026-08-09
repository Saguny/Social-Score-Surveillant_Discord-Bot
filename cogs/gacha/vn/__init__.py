from .cog import VNCog


async def setup(bot):
    await bot.add_cog(VNCog(bot))
