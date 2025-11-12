"""
Main script for running batch processing with async support
"""

import sys
import asyncio
import argparse
from src.batch_processor import BatchProcessor
from src.json_exporter import JSONExporter
from src.storage_uploader import StorageUploader


async def run_batch_processing(args):
    """Main async function for batch processing"""

    # Initialize processor
    processor = BatchProcessor()
    await processor.initialize()

    try:
        # Run processing based on mode
        print("=" * 60)
        print("Movie Post-Credits Batch Processor")
        print("=" * 60)

        if args.mode == "recent":
            await processor.process_tier("recent")

        elif args.mode == "theaters":
            await processor.process_tier("theaters")

        elif args.mode == "popular":
            await processor.process_tier("popular")

        elif args.mode == "all-tiers":
            await processor.process_all_tiers()

        elif args.mode == "specific":
            if not args.movie:
                print("Error: --movie argument required for specific mode")
                sys.exit(1)
            await processor.process_specific_movie(args.movie, args.year)

        elif args.mode == "update":
            tier = args.tier if args.tier else None
            await processor.update_existing_movies(tier)

        # Export data if requested
        if args.export:
            print("\n" + "=" * 60)
            print("Exporting data...")
            print("=" * 60)

            exporter = JSONExporter()
            await exporter.initialize()

            try:
                export_results = await exporter.export_all()
                print("\nExported files:")
                for tier_file in export_results["tier_files"]:
                    print(f"  - {tier_file}")
                print(f"  - {export_results['summary_file']}")
                print(f"  - {export_results['easter_eggs_file']}")
            finally:
                await exporter.close()

        # Upload to cloud storage if requested
        if args.upload:
            print("\n" + "=" * 60)
            print("Uploading to cloud storage...")
            print("=" * 60)

            uploader = StorageUploader()
            await uploader.upload_exports()

    finally:
        await processor.close()

    print("\n" + "=" * 60)
    print("Batch processing completed!")
    print("=" * 60)


def main():
    """Main entry point for batch processing"""
    parser = argparse.ArgumentParser(
        description="Movie Post-Credits Batch Processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process movies currently in theaters
  python -m src.run_batch --mode theaters --export --upload

  # Process popular movies
  python -m src.run_batch --mode popular --export

  # Process all tiers and export
  python -m src.run_batch --mode all-tiers --export --upload

  # Process a specific movie
  python -m src.run_batch --mode specific --movie "Dune" --year 2021

  # Update existing movies in database
  python -m src.run_batch --mode update --tier theaters
        """,
    )

    parser.add_argument(
        "--mode",
        choices=[
            "theaters", "popular", "recent", "all-tiers",
            "specific", "update"
        ],
        default="theaters",
        help="Processing mode",
    )

    parser.add_argument(
        "--tier", type=str, help="Specific tier to update"
    )

    parser.add_argument(
        "--movie", type=str, help="Specific movie title"
    )

    parser.add_argument(
        "--year", type=int, help="Movie year (optional)"
    )

    parser.add_argument(
        "--export", action="store_true", help="Export data to JSON"
    )

    parser.add_argument(
        "--upload", action="store_true", help="Upload to storage"
    )

    parser.add_argument(
        "--export-only", action="store_true", help="Export only"
    )

    args = parser.parse_args()

    # Handle export-only mode
    if args.export_only:

        async def export_only():
            exporter = JSONExporter()
            await exporter.initialize()
            try:
                await exporter.export_all()
                print("\nExport completed!")

                if args.upload:
                    uploader = StorageUploader()
                    await uploader.upload_exports()
            finally:
                await exporter.close()

        asyncio.run(export_only())
        return

    # Run batch processing
    asyncio.run(run_batch_processing(args))


if __name__ == "__main__":
    main()
