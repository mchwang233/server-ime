cmake_minimum_required(VERSION 3.18)
project(server_ime_engine VERSION 0.4.0 LANGUAGES NONE)
find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
enable_testing()
file(MAKE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/checks/mixed-revision")

add_custom_target(engine_bundle ALL
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/build_bundle.py"
          --output "${CMAKE_CURRENT_BINARY_DIR}/bundle"
  COMMENT "Verify pinned dependencies and assemble the Python/native runtime bundle"
  VERBATIM)

add_test(NAME engine_contract
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_engine.py")
add_test(NAME engine_enhanced
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_enhanced.py")
add_test(NAME engine_quality_revision
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_quality_revision.py")
add_test(NAME engine_composition
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_composition.py")
add_test(NAME engine_vendor_integrity
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/verify_vendor.py")
add_test(NAME engine_built_example
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_BINARY_DIR}/bundle/payload/engine/examples/python_client.py")
set_tests_properties(engine_contract engine_enhanced engine_quality_revision engine_composition engine_vendor_integrity engine_built_example
  PROPERTIES TIMEOUT 60 ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1")

set_tests_properties(engine_enhanced PROPERTIES ENVIRONMENT
  "PYTHONDONTWRITEBYTECODE=1;SERVER_IME_FEATURE_EVIDENCE=${CMAKE_CURRENT_SOURCE_DIR}/checks/mixed-revision/feature-matrix.json")
set_tests_properties(engine_quality_revision PROPERTIES ENVIRONMENT
  "PYTHONDONTWRITEBYTECODE=1;SERVER_IME_REVISION_EVIDENCE=${CMAKE_CURRENT_SOURCE_DIR}/checks/mixed-revision/revision-features.json")
set_tests_properties(engine_composition PROPERTIES ENVIRONMENT
  "PYTHONDONTWRITEBYTECODE=1;SERVER_IME_COMPOSITION_EVIDENCE=${CMAKE_CURRENT_SOURCE_DIR}/checks/mixed-revision/composition-features.json")

install(DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bundle/payload/engine/"
        DESTINATION share/server-ime/engine USE_SOURCE_PERMISSIONS)
install(PROGRAMS tools/installed_launcher.py DESTINATION bin RENAME server-ime-engine)
