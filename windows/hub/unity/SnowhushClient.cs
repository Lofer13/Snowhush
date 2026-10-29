// Snowhush client for Unity: tells the hub where the rectangles are that snow can settle on.
// No Unity types in here; it is plain .NET (needs the .NET Standard 2.1 API level, the default since Unity 2021).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Snowhush
{
    /// <summary>A rectangle in physical pixels of the virtual desktop, y pointing down, as Windows reports its windows.</summary>
    public struct SurfaceRect
    {
        public string Id;
        public float X, Y, Width, Height, Radius;
    }

    /// <summary>
    /// The connection to the hub, kept up on its own thread: it connects again when the hub was away and sends what the
    /// hub should know whenever that changed. One per source ("unity-game", "unity-editor"); a source's message replaces
    /// what it sent before.
    /// </summary>
    public sealed class SnowhushClient : IDisposable
    {
        public const string DefaultUrl = "ws://127.0.0.1:8765";

        readonly string source;
        readonly string url;
        readonly object gate = new object();
        string latest;
        string sent;
        volatile bool stop;

        public SnowhushClient(string source, string url = DefaultUrl)
        {
            this.source = source;
            this.url = url;
            Task.Run(Run);
        }

        /// <summary>
        /// What is on screen now, and the ids that are away for now (the program lost focus): Snowhush puts the snow of
        /// those aside as it is, and settles it again in the same place and the same amount when they are back in
        /// <paramref name="rects"/>. An id in neither list lets its snow fall.
        /// </summary>
        public void Set(IList<SurfaceRect> rects, IList<string> hidden)
        {
            string text = Build(source, rects, hidden);
            lock (gate) latest = text;
        }

        /// <summary>Takes all the snow off this source's rectangles: it falls.</summary>
        public void Clear()
        {
            string text = "{\"type\":\"clear\",\"source\":" + Quote(source) + "}";
            lock (gate) latest = text;
        }

        /// <summary>Gives the last message a moment to go out, then stops.</summary>
        public void Dispose()
        {
            for (int i = 0; i < 20 && !Flushed(); i++) Thread.Sleep(20);
            stop = true;
        }

        bool Flushed()
        {
            lock (gate) return latest == null || latest == sent;
        }

        async Task Run()
        {
            while (!stop)
            {
                try
                {
                    using (var socket = new ClientWebSocket())
                    {
                        using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3)))
                            await socket.ConnectAsync(new Uri(url), timeout.Token);
                        lock (gate) sent = null; // the hub may be a new one: it knows nothing yet
                        var reading = Drain(socket);
                        while (!stop && socket.State == WebSocketState.Open)
                        {
                            string next;
                            lock (gate) next = latest;
                            if (next != null && next != sent)
                            {
                                var bytes = Encoding.UTF8.GetBytes(next);
                                await socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, CancellationToken.None);
                                lock (gate) sent = next;
                            }
                            else
                            {
                                await Task.Delay(15);
                            }
                        }
                        if (socket.State == WebSocketState.Open)
                            await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None);
                        await reading;
                    }
                }
                catch (Exception)
                {
                    // No hub yet, or it went away: try again below.
                }
                if (!stop) await Task.Delay(1000);
            }
        }

        /// <summary>The hub passes on what the others send; nobody here wants it, but it has to be read or it piles up.</summary>
        static async Task Drain(ClientWebSocket socket)
        {
            var buffer = new byte[4096];
            try
            {
                while (socket.State == WebSocketState.Open)
                {
                    var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);
                    if (result.MessageType == WebSocketMessageType.Close) break;
                }
            }
            catch (Exception)
            {
            }
        }

        static string Build(string source, IList<SurfaceRect> rects, IList<string> hidden)
        {
            var text = new StringBuilder(128 + 96 * (rects?.Count ?? 0));
            text.Append("{\"type\":\"surfaces\",\"source\":").Append(Quote(source)).Append(",\"rects\":[");
            for (int i = 0; rects != null && i < rects.Count; i++)
            {
                SurfaceRect r = rects[i];
                if (i > 0) text.Append(',');
                text.Append("{\"id\":").Append(Quote(r.Id))
                    .Append(",\"x\":").Append(Number(r.X)).Append(",\"y\":").Append(Number(r.Y))
                    .Append(",\"w\":").Append(Number(r.Width)).Append(",\"h\":").Append(Number(r.Height))
                    .Append(",\"radius\":").Append(Number(r.Radius)).Append('}');
            }
            text.Append("],\"hidden\":[");
            for (int i = 0; hidden != null && i < hidden.Count; i++)
            {
                if (i > 0) text.Append(',');
                text.Append(Quote(hidden[i]));
            }
            return text.Append("]}").ToString();
        }

        static string Number(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value)) value = 0;
            return Math.Round(value, 1).ToString("0.0", CultureInfo.InvariantCulture);
        }

        static string Quote(string value)
        {
            var text = new StringBuilder("\"");
            foreach (char c in value ?? "")
            {
                if (c == '"' || c == '\\') text.Append('\\').Append(c);
                else if (c < ' ') text.Append("\\u").Append(((int)c).ToString("x4"));
                else text.Append(c);
            }
            return text.Append('"').ToString();
        }
    }
}
