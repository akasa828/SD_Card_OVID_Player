import 'dart:convert';

import 'package:desktop_drop/desktop_drop.dart';
import 'package:flet/flet.dart';
import 'package:flutter/material.dart';

class FletDropZoneControl extends StatefulWidget {
  final Control control;

  const FletDropZoneControl({super.key, required this.control});

  @override
  State<FletDropZoneControl> createState() => _FletDropZoneControlState();
}

class _FletDropZoneControlState extends State<FletDropZoneControl> {
  bool dragging = false;

  void setDragging(bool value) {
    if (dragging == value) return;
    setState(() => dragging = value);
    widget.control.triggerEvent('hover_change', value ? 'true' : 'false');
  }

  @override
  Widget build(BuildContext context) {
    final control = widget.control;
    final message = control.getString('message', '将素材拖到这里')!;
    final activeMessage = control.getString('active_message', '松开鼠标以添加素材')!;
    final background =
        control.getColor('background_color', context) ?? const Color(0x0F000000);
    final active =
        control.getColor('active_color', context) ?? const Color(0x246750A4);
    final foreground =
        control.getColor('foreground_color', context) ?? const Color(0xFF6750A4);
    final border =
        control.getColor('border_color', context) ?? const Color(0xFF79747E);

    final child = DropTarget(
      onDragEntered: (_) => setDragging(true),
      onDragExited: (_) => setDragging(false),
      onDragDone: (detail) {
        setDragging(false);
        control.triggerEvent(
          'drop',
          jsonEncode(detail.files.map((file) => file.path).toList()),
        );
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 140),
        constraints: const BoxConstraints(minHeight: 76),
        decoration: BoxDecoration(
          color: dragging ? active : background,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: foreground, width: dragging ? 2 : 1),
        ),
        child: Center(
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.file_download_outlined, color: foreground),
              const SizedBox(width: 10),
              Flexible(
                child: Text(
                  dragging ? activeMessage : message,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: dragging ? foreground : border),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    return LayoutControl(control: control, child: child);
  }
}
