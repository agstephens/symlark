"""Main module."""

__author__ = """Diane Knappett"""
__contact__ = 'diane.knappett@stfc.ac.uk'
__copyright__ = "Copyright 2020 United Kingdom Research and Innovation"
__license__ = "BSD - see LICENSE file in top-level package directory"

import os, glob, re
import hashlib
from pathlib import Path

import logging

# Set up module-level logger
logging.basicConfig()
logger = logging.getLogger(__name__)


def nested_list(d: str, remove_base=False) -> list:
    r = []
    for i in os.listdir(d):

        pth = os.path.join(d, i)
        if os.path.isdir(pth):
            r.extend(nested_list(pth))
        else:
            if remove_base:
                pth = pth.replace(remove_base, "")
            r.append(pth)

    return sorted(r)


def dirs_match(d1: str, d2: str, basedir1: str, basedir2: str) -> bool:
    errs = 0
    l1 = nested_list(d1, remove_base=basedir1)
    l2 = nested_list(d2, remove_base=basedir2)

    if l1 != l2:
        logger.error(f"Dirs have different listed contents: {d1} vs {d2}")
        return

    for i in d1:
        i1 = os.path.join(d1, i)
        i2 = os.path.join(d2, i)

        if os.path.isfile(i1):
            s1, s2 = [size(item) for item in (i1, i2)]
            if s1 != s2:
                logger.error(f"Files differ in size: {i1} = {s1} vs {i2} = {s2}")
                errs += 1
            else:
                m1, m2 = [md5(item) for item in (i1, i2)]
                if m1 != m2:
                    logger.error(f"Files differ in MD5: {i1} vs {i2}")
                    errs += 1

    res = True if errs == 0 else False
    return res    


def delete_dir(dr):
    logger.warning(f"Deleting files in: {dr}")
    for fname in os.listdir(dr):
        os.remove(f"{dr}/{fname}")

    logger.warning(f"Deleting directory: {dr}")
    os.rmdir(dr)


def symlink(target, symlink):
    logger.warning(f"Symlinking {symlink} to: {target}")
    os.symlink(target, symlink) 


def md5(f: str, blocksize: int=65536) -> str:
    hash = hashlib.md5()

    with open(f, "rb") as f:
        for block in iter(lambda: f.read(blocksize), b""):
            hash.update(block)
    return hash.hexdigest()


def size(f: str) -> int:
    return os.path.getsize(f)


def identify_dirs(d: str, pattern: str=r"v\d{8}") -> list:
    r = []
    for dr, subdirs, files in os.walk(d):
        if any([re.match(pattern, sdir) for sdir in subdirs]):
            r.append(dr)

    return r


def find_versions(dr):
    return sorted([os.path.basename(v) for v in glob.glob(f"{dr}/v????????")])


class VersionDir:
    def __init__(self, dr):
        self.dr = dr
        self.as_path = Path(dr)
        self.base, self.version = os.path.split(dr)


class ArchiveDir:
    def __init__(self, dr):
        self.dr = dr
        self.exists = os.path.isdir(dr)
        self.versions = find_versions(dr)
        self._latest_path = Path(f"{dr}/latest")
        self.latest = self._latest_path.readlink().as_posix() if self._latest_path.is_symlink() else False
        self._check_valid()

    def _check_valid(self):
        valid = True
        if not os.path.isdir(self.dr):
            valid = False
            logger.error(f"Archive container directory is missing: {self.dr}")
        elif not self.versions:
            valid = False
            logger.error(f"No version directories found in container directory: {self.dr}")
        
        if not self.latest:
            valid = False
            logger.error(f"No latest link in container directory: {self.dr}")
        elif self._latest_path.readlink().as_posix() != self.versions[-1]:
            valid = False
            logger.error(f"Latest link is not pointing to most recent version in: {self.dr}")

        self.valid = valid


def main(bd1: str, bd2: str) -> None:

    for dr in (bd1, bd2):
        if not os.path.isdir(dr):
            logger.error(f"Top-level directory does not exist: {dr}")
            return

    dirs_to_check = identify_dirs(bd1)

    if not dirs_to_check:
        logger.error(f"No content found in directory: {bd1}")

    for d1 in dirs_to_check:
        gws_dir = VersionDir(d1)
        gws_versions = find_versions(gws_dir.dr)

        arc_dir = ArchiveDir(d1.replace(bd1, bd2))

        # If archive dir is invalid then needs fixing before other checks can be done
        if not arc_dir.valid:
            continue

        # Loop through all GWS versions and check them
        for gws_version in reversed(gws_versions):
            gv_path, av_path = [os.path.join(bdir, gws_version) for bdir in (gws_dir.dr, arc_dir.dr)]
            logger.debug(f"[INFO] Working on: {gv_path}")
            logger.debug(f"              and: {av_path}")

            # If the GWS version is older than the latest archive version: delete the GWS version
            if gws_version < arc_dir.latest:
                delete_dir(gv_path)
                symlink(av_path, gv_path)
                logger.warning(f"[ACTION] Deleted old version in GWS: {gv_path}")
            
            # If they are the same:
            elif gws_version == arc_dir.latest:

                # TODO: find a better solution than ".endswith(av_path)" - should match equivalence
                if Path(gv_path).is_symlink() and Path(gv_path).readlink().as_posix().endswith(av_path):
                    logger.info(f"{gv_path} correctly points to: {av_path}")
                elif dirs_match(gv_path, av_path, bd1, bd2):
                    delete_dir(gv_path)
                    symlink(av_path, gv_path)
                    logger.warning(f"[ACTION] Deleted {gv_path} and symlinked to: {av_path}")

                arc_latest_link=Path(arc_dir.dr + '/latest')
                logger.warning(f"    Archive latest link points to {arc_latest_link.readlink()}")

                gws_latest_link=Path(gws_dir.dr + '/latest')
                if os.path.exists(gws_latest_link):
                    logger.warning(f"    GWS latest link points to {gws_latest_link.readlink()}")
                else:
                    logger.warning(f"    No latest link exists for {gv_path}")                

            # If the GWS version is newer: then maybe this is ready for ingestion, or needs attention
            else:
                logger.warning(f"GWS version is newer than archive dir: {gv_path} newer than {arc_dir.dr}/{arc_dir.latest}")
                latest_link=Path(gws_dir.dr + '/latest')
                if os.path.exists(latest_link):
                    logger.warning(f"    And latest link points to {latest_link.readlink()}")
                else:
                    logger.warning(f"    No latest link exists for {gv_path}")


