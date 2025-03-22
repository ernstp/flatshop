#!/usr/bin/env python3
import gi
gi.require_version("AppStream", "1.0")
gi.require_version("Flatpak", "1.0")

from gi.repository import Flatpak, GLib, Gio, AppStream
from pathlib import Path
import logging
from enum import IntEnum
from pathlib import Path
import argparse
import sys

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Match(IntEnum):
    NAME = 1
    ID = 2
    SUMMARY = 3
    NONE = 4


class AppStreamPackage:
    def __init__(self, comp: AppStream.Component, remote: Flatpak.Remote) -> None:
        self.component: AppStream.Component = comp
        self.remote: Flatpak.Remote = remote
        self.repo_name: str = remote.get_name()
        bundle: AppStream.Bundle = comp.get_bundle(AppStream.BundleKind.FLATPAK)
        self.flatpak_bundle: str = bundle.get_id()
        self.match = Match.NONE

        # Get icon and description
        self.icon_url = self._get_icon_url()
        self.icon_path_128 = self._get_icon_cache_path("128x128")
        self.icon_path_64 = self._get_icon_cache_path("64x64")
        self.icon_filename = self._get_icon_filename()
        self.description = self.component.get_description()

        # Get URLs from the component
        self.urls = self._get_urls()

        self.developer = self.component.get_developer().get_name()
        self.categories = self._get_categories()

    @property
    def id(self) -> str:
        return self.component.get_id()

    @property
    def name(self) -> str:
        return self.component.get_name()

    @property
    def summary(self) -> str:
        return self.component.get_summary()

    @property
    def version(self) -> str:
        releases = self.component.get_releases_plain()
        if releases:
            release = releases.index_safe(0)
            if release:
                version = release.get_version()
                return version
        return None

    def _get_icon_url(self) -> str:
        """Get the remote icon URL from the component"""
        icons = self.component.get_icons()

        # Find the first REMOTE icon
        remote_icon = next((icon for icon in icons if icon.get_kind() == AppStream.IconKind.REMOTE), None)
        return remote_icon.get_url() if remote_icon else ""

    def _get_icon_filename(self) -> str:
        """Get the cached icon filename from the component"""
        icons = self.component.get_icons()

        # Find the first CACHED icon
        cached_icon = next((icon for icon in icons if icon.get_kind() == AppStream.IconKind.CACHED), None)
        return cached_icon.get_filename() if cached_icon else ""

    def _get_icon_cache_path(self, size: str) -> str:

        # Remove the file:// prefix
        icon_filename = self._get_icon_filename()

        # Appstream icon cache path for the flatpak repo queried
        icon_cache_path = Path(self.remote.get_appstream_dir().get_path() + "/icons/flatpak/" + size + "/")
        return str(icon_cache_path)

    def _get_urls(self) -> dict:
        """Get URLs from the component"""
        urls = {
            'donation': self._get_url('donation'),
            'homepage': self._get_url('homepage'),
            'bugtracker': self._get_url('bugtracker')
        }
        return urls

    def _get_url(self, url_kind: str) -> str:
        """Helper method to get a specific URL type"""
        # Convert string to AppStream.UrlKind enum
        url_kind_enum = getattr(AppStream.UrlKind, url_kind.upper())
        url = self.component.get_url(url_kind_enum)
        if url:
            return url
        return ""

    def _get_categories(self) -> list:
        categories_fetch = self.component.get_categories()
        categories = []
        for category in categories_fetch:
            categories.append(category.lower())
        return categories

    def search(self, keyword: str) -> Match:
        """Search for keyword in package details"""
        if keyword in self.name.lower():
            return Match.NAME
        elif keyword in self.id.lower():
            return Match.ID
        elif keyword in self.summary.lower():
            return Match.SUMMARY
        else:
            return Match.NONE

    def __str__(self) -> str:
        return f"{self.name} - {self.summary} ({self.flatpak_bundle})"

    def get_details(self) -> dict:
        """Get all package details including icon and description"""
        return {
            "name": self.name,
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "version": self.version,
            "icon_url": self.icon_url,
            "icon_path_128": self.icon_path_128,
            "icon_path_64": self.icon_path_64,
            "icon_filename": self.icon_filename,
            "urls": self.urls,
            "developer": self.developer,
            #"architectures": self.architectures,
            "categories": self.categories,
            "bundle_id": self.flatpak_bundle,
            "match_type": self.match.name,
            "repo": self.repo_name
        }

class AppstreamSearcher:
    """Flatpak AppStream Package seacher"""

    def __init__(self) -> None:
        self.remotes: dict[str, list[AppStreamPackage]] = {}
        self.installed = []

    def add_installation(self, inst: Flatpak.Installation):
        """Add enabled flatpak repositories from Flatpak.Installation"""
        remotes = inst.list_remotes()
        for remote in remotes:
            if not remote.get_disabled():
                self.add_remote(remote, inst)

    def add_remote(self, remote: Flatpak.Remote, inst: Flatpak.Installation):
        """Add packages for a given Flatpak.Remote"""
        remote_name = remote.get_name()
        self.installed.extend([ref.format_ref() for ref in inst.list_installed_refs_by_kind(Flatpak.RefKind.APP)])
        if remote_name not in self.remotes:
            self.remotes[remote_name] = self._load_appstream_metadata(remote)

    def _load_appstream_metadata(self, remote: Flatpak.Remote) -> list[AppStreamPackage]:
        """load AppStrean metadata and create AppStreamPackage objects"""
        packages = []
        metadata = AppStream.Metadata.new()
        metadata.set_format_style(AppStream.FormatStyle.CATALOG)
        appstream_file = Path(remote.get_appstream_dir().get_path() + "/appstream.xml.gz")
        if appstream_file.exists():
            metadata.parse_file(Gio.File.new_for_path(appstream_file.as_posix()), AppStream.FormatKind.XML)
            components: AppStream.ComponentBox = metadata.get_components()
            i = 0
            for i in range(components.get_size()):
                component = components.index_safe(i)
                if component.get_kind() == AppStream.ComponentKind.DESKTOP_APP:
                    bundle = component.get_bundle(AppStream.BundleKind.FLATPAK).get_id()
                    if bundle not in self.installed:
                        packages.append(AppStreamPackage(component, remote))
            return packages
        else:
            logger.debug(f"AppStream file not found: {appstream_file}")
            return []

    def search_flatpak_repo(self, keyword: str, repo_name: str) -> list[AppStreamPackage]:
        search_results = []
        packages = self.remotes[repo_name]
        for package in packages:
            found = package.search(keyword)
            if found != Match.NONE:
                logger.debug(f" found : {package} match: {found}")
                package.match = found
                search_results.append(package)
        return search_results


    def search_flatpak(self, keyword: str, repo_name=None) -> list[AppStreamPackage]:
        """Search packages matching a keyword"""
        search_results = []
        keyword = keyword.lower()
        if repo_name:
            search_results = self.search_flatpak_repo(keyword, repo_name)
        else:
            for remote_name in self.remotes.keys():
                results = self.search_flatpak_repo(keyword, remote_name)
                for result in results:
                    search_results.append(result)
        return search_results

def main():
    """Main function demonstrating Flatpak information retrieval"""

    parser = argparse.ArgumentParser(description='Search Flatpak packages')
    parser.add_argument('--id', help='Application ID to search for')
    parser.add_argument('--repo', help='Filter results to specific repository')

    args = parser.parse_args()
    app_id = args.id
    repo_filter = args.repo

    if not app_id:
        print("Usage: python flatpak_info.py --<option> <value>")
        print("options: --id --repo")
        print("example (app search single repo): --id net.lutris.Lutris --repo flathub")
        print("example (app search all repos): --id net.lutris.Lutris")
        return


    # Create AppstreamSearcher instance
    searcher = AppstreamSearcher()

    # Add installations
    installation = Flatpak.Installation.new_system(None)
    searcher.add_installation(installation)

    if app_id == "" or len(app_id) < 3:
        self._clear()
        return

    logger.debug(f"(flatpak_search) key: {app_id}")

    # Now you can call search method on the searcher instance
    if repo_filter:
        search_results = searcher.search_flatpak(app_id, repo_filter)
    else:
        search_results = searcher.search_flatpak(app_id)
    if search_results:
        for package in search_results:
            details = package.get_details()
            print(f"Name: {details['name']}")
            print(f"ID: {details['id']}")
            print(f"Summary: {details['summary']}")
            print(f"Description: {details['description']}")
            print(f"Version: {details['version']}")
            print(f"Icon URL: {details['icon_url']}")
            print(f"Icon PATH 128x128: {details['icon_path_128']}")
            print(f"Icon PATH 64x64: {details['icon_path_64']}")
            print(f"Icon FILE: {details['icon_filename']}")
            print(f"Developer: {details['developer']}")
            print(f"Categories: {details['categories']}")

            urls = details['urls']
            print(f"Donation URL: {urls['donation']}")
            print(f"Homepage URL: {urls['homepage']}")
            print(f"Bug Tracker URL: {urls['bugtracker']}")

            print(f"Bundle ID: {details['bundle_id']}")
            print(f"Match Type: {details['match_type']}")
            print(f"Repo: {details['repo']}")
            print("-" * 50)
    return

if __name__ == "__main__":
    main()

