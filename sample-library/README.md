# Mac test sample library

`photos/` contains four reduced-size JPEG derivatives used as private seed
material for local interface and pipeline testing. They are not production
originals and contain no GPS, camera serial number, owner name, comments, or
embedded thumbnails.

On macOS, `start-mac-test.sh` expands these seeds locally into 28 deterministic
JPEG fixtures under the ignored `runtime/mac-test` directory. The generated
set contains fictional events, short similar bursts, varied exposure metadata,
all four registered lenses, and two exact duplicates. Generated files are not
committed.

Do not place production RAW files or private catalogs in this directory.
