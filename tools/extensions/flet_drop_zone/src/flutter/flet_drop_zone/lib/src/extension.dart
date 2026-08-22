import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

import 'flet_drop_zone.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    switch (control.type) {
      case 'FletDropZone':
        return FletDropZoneControl(key: key, control: control);
      default:
        return null;
    }
  }
}
