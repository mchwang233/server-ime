# libime runtime (full-pinyin decoding and next-word prediction)

- libime 1.1.11 (https://github.com/fcitx/libime, LGPL-2.1-or-later), release tarball
  `libime-1.1.11.tar.zst` from download.fcitx-im.org, built with C++20 on GCC 11.
  The fcitx4 migration tools are left out of the build (they need a newer fcitx5).
- Data from libime 1.1.17's release: `dict-20260907` (sc.dict, extb.dict) and
  `lm_sc.arpa-20260629` (zh_CN.lm, zh_CN.lm.predict), built by libime's own tools.
- libFcitx5Utils from fcitx5 5.1.12 (LGPL-2.1-or-later), built without X11,
  Wayland, DBus or an event loop; fmt 10.2.1 (MIT) compiled in.
- `lib/libsime_libime.so` is built from `engine/native/sime_libime.cpp`:

      g++ -std=c++20 -O2 -fPIC -shared -o lib/libsime_libime.so ../../native/sime_libime.cpp \
          -I<prefix>/include/LibIME -I<prefix>/include/Fcitx5/Utils -Llib \
          -lIMEPinyin -lIMECore -lFcitx5Utils -Wl,-rpath,'$ORIGIN'

Runtime needs the system's libboost_iostreams 1.75 and libzstd (both in EL9 base).
Licenses: `licenses/`.
