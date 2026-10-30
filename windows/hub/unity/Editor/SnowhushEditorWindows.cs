// Snowhush for the Unity Editor: snow settles on the top edge of the Editor's windows (Scene, Game, Inspector, ...).
// Starts by itself; nothing to add to a scene. Goes away while another program has the focus and comes back the same.
#if UNITY_EDITOR
using System.Collections.Generic;
using System.Reflection;
using UnityEditor;
using UnityEditorInternal;
using UnityEngine;

namespace Snowhush.Editor
{
    [InitializeOnLoad]
    static class SnowhushEditorWindows
    {
        // A window's `position` starts under its tab, and the snow rests on the top of the tab: this much higher, in points.
        // If the snow floats above the tabs or sinks into them, this is where to correct it.
        const float TabHeightPoints = 21f;
        const float MinWidthPoints = 80f;
        const float MinHeightPoints = 40f;

        static readonly SnowhushClient client = new SnowhushClient("unity-editor");
        static readonly List<SurfaceRect> rects = new List<SurfaceRect>();
        static readonly List<string> ids = new List<string>();
        static readonly List<string> none = new List<string>();
        static readonly FieldInfo parentField = typeof(UnityEditor.EditorWindow).GetField("m_Parent", BindingFlags.Instance | BindingFlags.NonPublic);
        static bool focused = InternalEditorUtility.isApplicationActive;
        static double next;

        static SnowhushEditorWindows()
        {
            EditorApplication.update += Tick;
            // Scripts recompile in a moment and this goes away: the snow waits, and is back with the same windows.
            AssemblyReloadEvents.beforeAssemblyReload += () =>
            {
                client.Set(new List<SurfaceRect>(), ids);
                client.Dispose();
            };
            EditorApplication.quitting += () =>
            {
                client.Clear();
                client.Dispose();
            };
        }

        static void Tick()
        {
            if (EditorApplication.timeSinceStartup < next) return;
            next = EditorApplication.timeSinceStartup + 0.05;
            // Asked every time instead of waiting for an event: the ones that say the Editor lost the focus
            // (EditorApplication.focusChanged) don't exist in every version of Unity.
            bool active = InternalEditorUtility.isApplicationActive;
            if (!active)
            {
                if (focused)
                {
                    focused = false;
                    client.Set(new List<SurfaceRect>(), ids); // away: the snow waits where it is
                }
                return;
            }
            focused = true;
            Collect();
            client.Set(rects, none);
        }

        static void Collect()
        {
            rects.Clear();
            ids.Clear();
            float scale = EditorGUIUtility.pixelsPerPoint;
            foreach (UnityEditor.EditorWindow window in Resources.FindObjectsOfTypeAll<UnityEditor.EditorWindow>())
            {
                if (window == null || !IsShown(window)) continue;
                Rect position = window.position; // in points, on the screen
                if (position.width < MinWidthPoints || position.height < MinHeightPoints) continue;
                string id = "win-" + window.GetInstanceID();
                ids.Add(id);
                rects.Add(new SurfaceRect
                {
                    Id = id,
                    X = position.x * scale,
                    Y = (position.y - TabHeightPoints) * scale,
                    Width = position.width * scale,
                    Height = (position.height + TabHeightPoints) * scale,
                    Radius = 0f,
                });
            }
        }

        /// <summary>Whether this window is the tab showing in its dock, not one behind another.</summary>
        static bool IsShown(UnityEditor.EditorWindow window)
        {
            if (parentField == null) return true; // another Unity: no way to tell, report them all
            try
            {
                object parent = parentField.GetValue(window);
                if (parent == null) return false;
                PropertyInfo view = parent.GetType().GetProperty("actualView", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                return view == null || ReferenceEquals(view.GetValue(parent), window);
            }
            catch (System.Exception)
            {
                return true;
            }
        }
    }
}
#endif
