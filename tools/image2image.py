import time
import base64
import traceback
from collections.abc import Generator
from tkinter import image_names

import requests
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin import Tool
from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.images import SequentialImageGenerationOptions


class Image2ImageTool(Tool):
    @staticmethod
    def _encode_image(file_data):
        """将图片文件编码为base64"""
        try:
            # 记录图片大小
            image_size = len(file_data) / 1024  # KB
            encoded = base64.b64encode(file_data).decode("utf-8")
            encoded_size = len(encoded) / 1024  # KB
            debug_info = f"图片编码完成: 原始大小={image_size:.2f}KB, 编码后大小={encoded_size:.2f}KB"
            return encoded, debug_info
        except Exception as e:
            stack_trace = traceback.format_exc()
            raise Exception(f"图片编码失败: {str(e)}\n堆栈跟踪: {stack_trace}")

    def _invoke(
        self, tool_parameters: dict
    ) -> Generator[ToolInvokeMessage, None, None]:
        """
        Invoke image-to-image generation tool using Doubao AI
        
        Parameters:
            tool_parameters (dict): Dictionary containing:
                - prompt (str): Text description for video generation
                - image (file): Image file to be used for video generation
                - duration (str): Video duration in seconds
                - ratio (str): Aspect ratio (e.g., "16:9")
        
        Returns:
            Generator[ToolInvokeMessage, None, None]: Messages including video generation progress and final video URL
        """
        # 获取API key
        api_key = self.runtime.credentials.get("api_key")
        base_url = "https://ark.cn-beijing.volces.com/api/v3"

        # 获取图片文件
        image_files = tool_parameters.get("image")
        images_data = []
        if not image_files:
            images_data = None
        else:
            # 处理图片文件
            for image_file in image_files:
                try:
                    # 处理不同类型的图片输入
                    file_content = None

                    # 检查文件类型并获取文件内容
                    if hasattr(image_file, 'url') and image_file.url:
                        # 如果文件是通过URL提供的
                        file_url = image_file.url
                        yield self.create_text_message(f"正在从URL获取图片: {file_url[:30]}...")
                        try:
                            response = requests.get(file_url, timeout=60)
                            response.raise_for_status()
                            file_content = response.content
                            yield self.create_text_message(f"成功下载图片: 大小={len(file_content)/1024:.2f}KB")
                        except Exception as e:
                            yield self.create_text_message(f"从URL下载图片失败: {str(e)}")
                            return

                    # 如果URL下载失败或没有URL，尝试其他方法
                    if file_content is None and hasattr(image_file, 'blob'):
                        try:
                            file_content = image_file.blob
                            yield self.create_text_message(f"从blob属性获取文件数据: 大小={len(image_file.blob)/1024:.2f}KB")
                        except Exception as e:
                            yield self.create_text_message(f"获取blob属性失败: {str(e)}")

                    # 尝试从read方法获取
                    if file_content is None and hasattr(image_file, 'read'):
                        try:
                            file_content = image_file.read()
                            yield self.create_text_message("从可读对象获取文件数据")
                            # 如果是文件对象，可能需要重置文件指针
                            if hasattr(image_file, 'seek'):
                                image_file.seek(0)
                        except Exception as e:
                            yield self.create_text_message(f"从read方法获取文件数据失败: {str(e)}")

                    # 尝试作为文件路径处理
                    if file_content is None and isinstance(image_file, str):
                        try:
                            with open(image_file, 'rb') as f:
                                file_content = f.read()
                            yield self.create_text_message(f"从文件路径获取文件数据: {image_file}, 大小={len(file_content)/1024:.2f}KB")
                        except (TypeError, IOError) as e:
                            yield self.create_text_message(f"从文件路径获取文件数据失败: {str(e)}")

                    # 尝试本地文件缓存方式
                    if file_content is None and hasattr(image_file, 'path'):
                        try:
                            with open(image_file.path, 'rb') as f:
                                file_content = f.read()
                            yield self.create_text_message(f"从本地缓存路径获取文件数据: {image_file.path}, 大小={len(file_content)/1024:.2f}KB")
                        except (TypeError, IOError) as e:
                            yield self.create_text_message(f"从本地缓存路径获取文件数据失败: {str(e)}")

                    # 如果所有方法都失败
                    if file_content is None:
                        yield self.create_text_message("无法获取图片数据。请尝试重新上传图片或使用较小的图片文件")
                        return

                    # 编码图片数据为base64
                    try:
                        encoded_image, encoding_debug = self._encode_image(file_content)
                        yield self.create_text_message(encoding_debug)

                        # 构建图片URL (豆包API需要可访问的URL或base64数据)
                        image_data_url = f"data:image/jpeg;base64,{encoded_image}"
                        images_data.append(image_data_url)
                    except Exception as e:
                        yield self.create_text_message(f"图片编码失败: {str(e)}")
                        return

                except Exception as e:
                    stack_trace = traceback.format_exc()
                    yield self.create_text_message(f"处理图片文件失败: {str(e)}\n堆栈跟踪:\n{stack_trace}")
                    return
        
        prompt = tool_parameters.get("prompt")
        model = tool_parameters.get("model")
        image_size = tool_parameters.get("image_size")
        output_image_num = tool_parameters.get("output_image_num")

        try:
            yield self.create_text_message("准备生成图片...")
            yield self.create_text_message(f"提示词: {prompt}")
            client = Ark(base_url=base_url, api_key=api_key)
            images_stream_response = client.images.generate(
                model=model,
                prompt=prompt,
                image=images_data,
                size=image_size,
                sequential_image_generation="auto",
                sequential_image_generation_options=SequentialImageGenerationOptions(max_images=output_image_num),
                stream=True,
                response_format="url",
                watermark=False # 是否在生成的图片中添加水印
            )

            output_json = {}
            images_info = []
            yield self.create_text_message("正在等待图片生成...")
            for event in images_stream_response:
                if event is None:
                    continue
                if event.type == "image_generation.partial_failed":
                    yield self.create_text_message(f"image_generation.partial_failed. 部分图片生成失败, 错误信息: {event.error}")
                    if event.error is not None and event.error.code.equal("InternalServiceError"):
                        yield self.create_text_message(f"InternalServiceError 图片生成失败, 错误信息: {event.error}")
                        return
                elif event.type == "image_generation.partial_succeeded":
                    if event.error is None and event.url:
                        images_info.append(event)
                        yield self.create_text_message(f"第{event.image_index}张图片生成完成。该链接将在生成后 24 小时内失效，请务必及时保存图像。{event}")
                        yield self.create_image_message(event.url)
                elif event.type == "image_generation.completed":
                    if event.error is None:
                        yield self.create_text_message(f"图片生成完成")
                        output_json['images_info'] = images_info
                        output_json['usage'] = event.usage
                        yield self.create_json_message(output_json)
                elif event.type == "image_generation.partial_image":
                    images_info.append(event)
                    yield self.create_text_message(
                        f"第{event.image_index}张图片生成完成。该链接将在生成后 24 小时内失效，请务必及时保存图像。{event}")
                    yield self.create_image_message(event.url)
        
        except Exception as e:
            # 处理异常
            yield self.create_text_message(f"生成图片时出错: {str(e)}")
