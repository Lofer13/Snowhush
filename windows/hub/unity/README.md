# Snowhush for Unity

Two scripts that send rectangles to the hub, so snow settles on the top edge of

- **the Unity Editor's windows** (Scene, Game, Inspector, ...), with `Editor/SnowhushEditorWindows.cs`, and
- **UI elements in a built Windows player**, with `SnowhushSurface`.

Both go away while another program has the focus, and come back with the same snow in the same place.

## Install

1. Copy this folder into your project as `Assets/Snowhush/` (so the Editor script is in `Assets/Snowhush/Editor/`).
2. **Edit > Project Settings > Player > Other Settings > Api Compatibility Level: .NET Standard 2.1** (the default
   since Unity 2021). The client uses `System.Net.WebSockets`.
3. Start the hub (`python hub.py`) and Snowhush with `SNOWHUSH_HUB=ws://127.0.0.1:8765`.

The Editor windows work as soon as the scripts have compiled. For the game's UI, add the **Snowhush > Snow Surface**
component to the panels, buttons or images that should hold snow, and make a Windows build.

## Notes

- Not in the Editor's Play mode: the Game view is a panel in the Editor's window and Windows doesn't say where.
- The player has to be DPI aware (the default); otherwise Windows reports scaled coordinates that don't match.
- Rotated UI isn't followed: the rectangle it covers on the screen is used.
- The scripts were written without a Unity at hand and are not tried: a compile error or a coordinate that is off is
  likely at first. `python ../fake_client.py --mirror` outlines on the screen where the scripts say the rectangles are;
  `TabHeightPoints` in the Editor script is the thing to adjust if the snow floats above the window tabs or sinks
  into them.
