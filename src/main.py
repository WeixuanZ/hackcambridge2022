import json
from pathlib import Path
from random import randint
from typing import Callable, List

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from face_detector import FaceDetector
from structures import ImageData, Segment
from transcription import split_utterances, transcribe
from video_processor import Video
from frame_processor import StyleTransfer
from layout_generator import LayoutGenerator


DEBUG = True


def pipe(
    *functions: Callable[[Segment], None]
) -> Callable[[List[Segment]], List[Segment]]:
    """Implements function composition."""

    def pipeline(segments):
        for segment in segments:
            for function in functions:
                function(segment)

        return segments

    return pipeline


def attach_frames(video: Video):
    def attach_to_segment(segment: Segment) -> None:
        segment.frames = video.get_frames(segment.start, segment.end)

    return attach_to_segment


def get_key_frame_index(segment: Segment) -> None:
    segment.keyframe_index = randint(0, segment.frames.shape[0] - 1)


def detect_speaker(segment: Segment) -> None:
    face_detector = FaceDetector()

    segment.keyframe = segment.frames[segment.keyframe_index]
    segment.speaker_location, segment.speakers_bbox = face_detector.find_speaker_face(
        segment.keyframe
    )


def crop_keyframe(segment: Segment) -> None:
    subject_bbox_center = segment.speakers_bbox.center

    if subject_bbox_center[0] > segment.keyframe.shape[0] // 2:
        segment.keyframe = segment.keyframe[
            : int(segment.speakers_bbox.x + segment.speakers_bbox.width), :, :
        ]
    else:
        segment.keyframe = segment.keyframe[int(segment.speakers_bbox.x) :, :, :]

    if subject_bbox_center[1] > segment.keyframe.shape[1] // 2:
        segment.keyframe = segment.keyframe[
            :, : int(segment.speakers_bbox.y + segment.speakers_bbox.height), :
        ]
    else:
        segment.keyframe = segment.keyframe[:, int(segment.speakers_bbox.y) :, :]


def transfer_keyframe_style(segment: Segment) -> None:
    transfer_style = StyleTransfer()
    segment.keyframe = transfer_style(segment.keyframe)


def convert_keyframe_to_obj(segment: Segment) -> None:
    segment.image = ImageData(
        image_data_matrix=segment.keyframe, image_subject=segment.speakers_bbox
    )


async def main():
    video = Video("metaverse_short.mp4")
    utterances = split_utterances(await transcribe(video.audio))

    if DEBUG:
        with open("transcript.json", "w") as file:
            json.dump(utterances, file, indent=4)

    pipeline = pipe(
        attach_frames(video),
        get_key_frame_index,
        detect_speaker,
        crop_keyframe,
        transfer_keyframe_style,
        convert_keyframe_to_obj,
    )
    segments = pipeline(
        [Segment(**utterance_segment) for utterance_segment in utterances]
    )

    layout_generator = LayoutGenerator()
    for segment in segments:
        layout_generator.add_frame(segment)

    layout_generator.render_frames_to_image("test.png", 1000)


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"


@app.route("/", methods=["GET"])
def serve_home():
    return render_template("index.html")


@app.after_request
def chrome_connection_hack(resp):
    resp.headers["Connection"] = "close"
    return resp


@app.route("/api/submit", methods=["POST"])
def process_video():
    print(request.files)

    if "file" not in request.files:
        return abort(400)

    data = request.files["file"]

    path = Path(".") / app.config["UPLOAD_FOLDER"] / secure_filename(data.filename)
    with open(path.resolve(), "wb") as file:
        data.save(file)

    return redirect(url_for("static", filename="test.jpg"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True, threaded=True)
