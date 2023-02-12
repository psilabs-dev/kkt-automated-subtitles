import logging
import os.path
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .data_access_services import SubtitleDataAccessService
from .domain_models import Subtitle, SubtitleGroup
from .validate import validate_subtitle_group

logger = logging.getLogger(__name__)

def _get_text_dimensions(text_string, font):
    ascent, descent = font.getmetrics()

    text_width = font.getmask(text_string).getbbox()[2]
    text_height = font.getmask(text_string).getbbox()[3] + descent

    return text_width, text_height

def add_background(image:Image.Image, background_image) -> Image.Image:
    image.paste(background_image, (0, 0), background_image)
    return image

def apply_subtitle_to_image(image:Image.Image, subtitle:Subtitle) -> Image.Image:
    # applies data from the subtitle to the image.

    # expand subtitle.
    subtitle_profile = subtitle.subtitle_profile
    content = subtitle.content

    # expand details of subtitle profile.
    font_data = subtitle_profile.font_data
    outline_data_1 = subtitle_profile.outline_data_1
    outline_data_2 = subtitle_profile.outline_data_2
    textbox_data = subtitle_profile.textbox_data
    background_image_path = subtitle_profile.background_image_path

    # add background image (if any)
    if background_image_path is not None:
        background_image = Image.open(background_image_path)
        image = add_background(image, background_image)

    # extract image data
    image_width, image_height = image.size
    text_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_layer)
    outline_1_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    outline_1_draw = ImageDraw.Draw(outline_1_layer)
    outline_2_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    outline_2_draw = ImageDraw.Draw(outline_2_layer)

    # extract text data
    font_style = font_data.style
    font_color = font_data.color
    font_size = font_data.size
    font_stroke_size = font_data.stroke_size
    font_stroke_color = font_data.stroke_color
    alignment = textbox_data.alignment
    tb_anchor_x, tb_anchor_y = textbox_data.anchor_point
    box_width = textbox_data.box_width
    push = textbox_data.push

    # analyze text
    wrapped_text = [_line for line in content for _line in textwrap.wrap(line, width=box_width)]
    font = ImageFont.truetype(font_style, font_size)
    text_dimensions = [_get_text_dimensions(line, font) for line in wrapped_text]
    text_widths = list(map(lambda dim:dim[0], text_dimensions))
    max_text_width = max(text_widths)
    # this is used to standardize the heights of each horizontal text line, but might be a bad idea for different languages.
    # maybe use vertical spacing in the future to avoid font-dependent height definition...
    text_height = _get_text_dimensions("l", font)[1]
    num_lines = len(wrapped_text)
    sum_text_height = num_lines * text_height

    # add text.
    for i, line in enumerate(wrapped_text):
        text_width = font.getlength(line)

        if alignment == "left":
            x = (image_width + text_width)/2 + tb_anchor_x - text_width/2
        elif alignment == "center":
            x = image_width/2 + tb_anchor_x - text_width/2
        elif alignment == "right":
            x = (image_width - text_width)/2 + tb_anchor_x - text_width/2
        else:
            raise ValueError(f"Invalid alignment value {alignment}.")
        if push == "up":
            y = image_height/2 - tb_anchor_y + (- text_height*(num_lines-i))
        elif push == "down":
            y = image_height/2 - tb_anchor_y + (sum_text_height - text_height*(num_lines-i))
        else:
            raise ValueError(f"Invalid push value {push}.")
        line_pos = (x, y)

        if outline_data_2 is not None:
            outline_2_draw.text(
                line_pos, line, font=font, fill=outline_data_2.color, stroke_width=outline_data_2.radius,
                stroke_fill=outline_data_2.color
            )

        if outline_data_1 is not None:
            outline_1_draw.text(
                line_pos, line, font=font, fill=outline_data_1.color, stroke_width=outline_data_1.radius,
                stroke_fill=outline_data_1.color
            )

        # add text layer
        if font_data.stroke_size is not None:
            text_draw.text(line_pos, line, font=font, fill=font_color, stroke_width=font_stroke_size, stroke_fill=font_stroke_color)
            pass
        else:
            text_draw.text(line_pos, line, font=font, fill=font_color)
        image.paste(text_layer, (0, 0), text_layer)

    # apply paste
    if outline_data_2 is not None:
        if outline_data_2.blur_strength is not None and outline_data_2.blur_strength:
            outline_2_layer = outline_2_layer.filter(ImageFilter.GaussianBlur(radius=outline_data_2.blur_strength))
        image.paste(outline_2_layer, (0, 0), outline_2_layer)
    if outline_data_1 is not None:
        if outline_data_1.blur_strength is not None and outline_data_1.blur_strength:
            outline_1_layer = outline_1_layer.filter(ImageFilter.GaussianBlur(radius=outline_data_1.blur_strength))
        image.paste(outline_1_layer, (0, 0), outline_1_layer)

    image.paste(text_layer, (0, 0), text_layer)

    # add foreground image (if any)

    return image

class SubtitleService:
    def __init__(self, subtitle_model:SubtitleDataAccessService=None):
        self.subtitle_model = subtitle_model

    def apply_subtitle_group(self, subtitle_group:SubtitleGroup) -> Image.Image:
        image_id = subtitle_group.image_id
        subtitle_list = subtitle_group.subtitle_list
        image_path = os.path.join(self.subtitle_model.input_image_directory, image_id)
        image = Image.open(image_path).copy()
        for subtitle in subtitle_list:
            image = apply_subtitle_to_image(image, subtitle)
        return image

    def add_subtitles(self):
        subtitle_groups = self.subtitle_model.get_subtitle_groups()
        # validation layer here.
        for text_id in subtitle_groups.keys():
            for image_id in subtitle_groups.get(text_id).keys():
                validate_subtitle_group(subtitle_groups.get(text_id).get(image_id))

        image_paths = self.subtitle_model.get_image_paths()
        n = len(image_paths)

        for text_id in subtitle_groups.keys():
            subtitle_group_by_text_id = subtitle_groups[text_id]

            output_directory_by_text_id = os.path.join(
                self.subtitle_model.output_directory, os.path.splitext(os.path.basename(text_id))[0]
            )
            if not os.path.exists(output_directory_by_text_id):
                os.makedirs(output_directory_by_text_id)

            for i, image_path in enumerate(image_paths):
                image_id = os.path.basename(image_path)
                output_image_path = os.path.join(output_directory_by_text_id, image_id)
                if image_id in subtitle_group_by_text_id.keys():
                    subtitle_group = subtitle_group_by_text_id[image_id]
                    processed_image = self.apply_subtitle_group(subtitle_group)
                    processed_image.save(output_image_path)
                else:
                    Image.open(image_path).save(output_image_path)
                logger.info(f"Processed and saved image {i+1}/{n} for text_id {os.path.splitext(os.path.basename(text_id))[0]}.")

        pass

    pass