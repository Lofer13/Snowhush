// Snowhush for Unity, in-game UI: put SnowhushSurface on any UI element (a panel, a button, an image) and snow
// settles on its top edge, in a built Windows player. Needs no scene setup; a hidden object that reports the
// rectangles creates itself with the first surface.
//
// Not in the Editor's Play mode: the Game view is a panel inside the Editor's window and Windows doesn't say where.
// The Editor's own windows are the job of Editor/SnowhushEditorWindows.cs.
using System;
using System.Collections.Generic;
using UnityEngine;

namespace Snowhush
{
    [DisallowMultipleComponent]
    [RequireComponent(typeof(RectTransform))]
    [AddComponentMenu("Snowhush/Snow Surface")]
    public class SnowhushSurface : MonoBehaviour
    {
        [Tooltip("Corner radius of the element in screen pixels, so the snow follows a rounded edge.")]
        public float cornerRadius = 0f;

        static readonly List<SnowhushSurface> all = new List<SnowhushSurface>();
        internal static IReadOnlyList<SnowhushSurface> All => all;

        void OnEnable()
        {
            all.Add(this);
            SnowhushRunner.EnsureExists();
        }

        void OnDisable()
        {
            all.Remove(this);
        }
    }

    /// <summary>Reports the rectangles of all the SnowhushSurface in the scene, in pixels of the desktop.</summary>
    [AddComponentMenu("")]
    class SnowhushRunner : MonoBehaviour
    {
        static SnowhushRunner instance;

        readonly List<SurfaceRect> rects = new List<SurfaceRect>();
        readonly List<string> ids = new List<string>();
        readonly List<string> none = new List<string>();
        readonly Vector3[] corners = new Vector3[4];
        SnowhushClient client;
        bool focused = true;
        float next;

        internal static void EnsureExists()
        {
#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
            if (instance != null) return;
            var holder = new GameObject("Snowhush") { hideFlags = HideFlags.HideAndDontSave };
            DontDestroyOnLoad(holder);
            instance = holder.AddComponent<SnowhushRunner>();
#endif
        }

        void OnEnable()
        {
            client = new SnowhushClient("unity-game");
        }

        void OnDisable()
        {
            if (client != null) client.Dispose();
            client = null;
        }

        /// <summary>Away: the rectangles are taken off the screen but their snow is kept where it is.</summary>
        void OnApplicationFocus(bool hasFocus)
        {
            focused = hasFocus;
            if (client != null && !hasFocus) client.Set(new List<SurfaceRect>(), ids);
        }

        void LateUpdate()
        {
            if (client == null || !focused || Time.unscaledTime < next) return;
            next = Time.unscaledTime + 0.03f;
            Collect();
            client.Set(rects, none);
        }

        void Collect()
        {
            rects.Clear();
            ids.Clear();
            if (!WindowsClient.TryGet(out float left, out float top, out float width, out float height) || Screen.width < 1 || Screen.height < 1) return;
            float sx = width / Screen.width;
            float sy = height / Screen.height;
            foreach (SnowhushSurface surface in SnowhushSurface.All)
            {
                var rect = (RectTransform)surface.transform;
                var canvas = rect.GetComponentInParent<Canvas>();
                Camera camera = canvas != null && canvas.renderMode != RenderMode.ScreenSpaceOverlay ? canvas.worldCamera : null;
                rect.GetWorldCorners(corners); // bottom left, top left, top right, bottom right
                Vector2 a = RectTransformUtility.WorldToScreenPoint(camera, corners[0]);
                Vector2 b = RectTransformUtility.WorldToScreenPoint(camera, corners[2]);
                float x0 = Mathf.Min(a.x, b.x), x1 = Mathf.Max(a.x, b.x);
                float y0 = Mathf.Min(a.y, b.y), y1 = Mathf.Max(a.y, b.y); // Unity's y points up
                string id = "ui-" + surface.GetInstanceID();
                ids.Add(id);
                rects.Add(new SurfaceRect
                {
                    Id = id,
                    X = left + x0 * sx,
                    Y = top + (Screen.height - y1) * sy,
                    Width = (x1 - x0) * sx,
                    Height = (y1 - y0) * sy,
                    Radius = surface.cornerRadius * sx,
                });
            }
        }
    }

    /// <summary>Where the player's drawing area is on the desktop, in physical pixels.</summary>
    static class WindowsClient
    {
#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct Point { public int X, Y; }

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct Rect { public int Left, Top, Right, Bottom; }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool ClientToScreen(IntPtr window, ref Point point);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool GetClientRect(IntPtr window, out Rect rect);

        static IntPtr window;
        static float looked;

        static IntPtr Window()
        {
            if (window == IntPtr.Zero && Time.unscaledTime - looked > 1f)
            {
                looked = Time.unscaledTime;
                var process = System.Diagnostics.Process.GetCurrentProcess();
                process.Refresh();
                window = process.MainWindowHandle;
            }
            return window;
        }
#endif

        public static bool TryGet(out float left, out float top, out float width, out float height)
        {
            left = top = width = height = 0;
#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
            IntPtr handle = Window();
            if (handle == IntPtr.Zero) return false;
            var origin = new Point();
            if (!ClientToScreen(handle, ref origin) || !GetClientRect(handle, out Rect size)) return false;
            left = origin.X;
            top = origin.Y;
            width = size.Right - size.Left;
            height = size.Bottom - size.Top;
            return width > 0 && height > 0;
#else
            return false;
#endif
        }
    }
}
