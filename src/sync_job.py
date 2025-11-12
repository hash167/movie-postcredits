"""
Background sync job to keep on-demand JSON in MinIO synchronized with database
"""

import asyncio
from datetime import datetime
from src.database import DatabaseManager
from src.json_exporter import JSONExporter
from src.storage_uploader import StorageUploader


class SyncJob:
    """Periodically sync database to MinIO on-demand JSON"""

    def __init__(self, interval_seconds: int = 300):  # Default: every 5 minutes
        self.interval = interval_seconds
        self.db = DatabaseManager()
        self.exporter = JSONExporter()
        self.uploader = StorageUploader()
        self.running = False

    async def initialize(self):
        """Initialize database connection"""
        await self.db.connect()
        await self.exporter.initialize()

    async def close(self):
        """Close connections"""
        await self.db.close()
        await self.exporter.close()

    async def sync_once(self):
        """Run sync once"""
        try:
            print(f"\n{'='*60}")
            print(f"🔄 Sync Job - {datetime.now().isoformat()}")
            print(f"{'='*60}")

            # Check if there are any on-demand movies with content
            async with self.db.pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT m.id)
                    FROM movies m
                    WHERE m.tier = 'on-demand'
                    AND (
                        EXISTS (
                            SELECT 1 FROM post_credits pc 
                            WHERE pc.movie_id = m.id AND pc.has_scene = TRUE
                        )
                        OR EXISTS (
                            SELECT 1 FROM easter_eggs ee 
                            WHERE ee.movie_id = m.id
                        )
                    )
                    """
                )

            if count == 0:
                print("  ℹ️  No on-demand movies with content to sync")
                print(f"{'='*60}\n")
                return

            print(f"  📊 Found {count} on-demand movies with content")

            # Export on-demand tier
            print("  📤 Exporting on-demand tier...")
            filepath = await self.exporter.export_tier("on-demand")

            # Upload to MinIO
            print("  ☁️  Uploading to MinIO...")
            success = await self.uploader.upload_file(filepath)

            if success:
                print(f"  ✅ Sync complete! {count} movies available in MinIO")
            else:
                print("  ❌ Upload failed")

            print(f"{'='*60}\n")

        except Exception as e:
            print(f"  ❌ Sync error: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")

    async def start(self):
        """Start the background sync job"""
        self.running = True
        print(f"🚀 Starting sync job (interval: {self.interval}s)")

        await self.initialize()

        # Run initial sync
        await self.sync_once()

        # Then run periodically
        while self.running:
            await asyncio.sleep(self.interval)
            if self.running:
                await self.sync_once()

    async def stop(self):
        """Stop the sync job"""
        print("⏹️  Stopping sync job...")
        self.running = False
        await self.close()


# Singleton instance
sync_job = SyncJob(interval_seconds=300)  # Sync every 5 minutes

