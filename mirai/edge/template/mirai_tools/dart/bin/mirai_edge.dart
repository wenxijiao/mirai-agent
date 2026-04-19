import 'dart:async';

import 'package:mirai_edge/mirai_setup.dart';

Future<void> main() async {
  initMirai();
  // ignore: avoid_print
  print('Mirai edge running. Press Ctrl+C to stop.');
  await Future<void>.delayed(const Duration(days: 365));
}
