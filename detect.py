from __future__ import print_function

import argparse

import cv2
from arc_face import *
import torch
import numpy as np
import torch.backends.cudnn as cudnn
from torch.nn import DataParallel

from utils import google_utils
from utils.datasets import *
from utils.utils import *

from silentFace_model.predict_net import *
from silentFace_model.predict_net import AntiSpoofPredict

from PIL import Image, ImageDraw, ImageFont

def cv2_letterbox_image(image, expected_size):
    ih, iw = image.shape[0:2]
    ew, eh = expected_size,expected_size
    scale = max(eh / ih, ew / iw) # 最大边缩放至608的比例
    nh = int(ih * scale)
    nw = int(iw * scale)
    image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_CUBIC) # 等比例缩放，使得有一边608
    top = (eh - nh) // 2 # 上部分填充的高度
    bottom = eh - nh - top  # 下部分填充的高度
    left = (ew - nw) // 2 # 左部分填充的距离
    right = ew - nw - left # 右部分填充的距离
    # 边界填充
    new_img = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT)
    return new_img

def cosin_metric(x1, x2):
    #计算余弦距离
    return np.dot(x1, x2) / (np.linalg.norm(x1) * np.linalg.norm(x2))

def load_image(img_path):
    image = cv2.imread(img_path, 0)
    if image is None:
        return None
    # image = cv2_letterbox_image(image,128)
    image = cv2.resize(image,(128,128))
    image = np.dstack((image, np.fliplr(image)))
    image = image.transpose((2, 0, 1))
    image = image[:, np.newaxis, :, :]
    image = image.astype(np.float32, copy=False)
    image -= 127.5
    image /= 127.5
    return image

#与ArcFace结合使用
def get_featuresdict(model, dir):# model为ArcFace模型，dir为数据库的目录。
    list = os.listdir(dir)
    person_dict = {}
    for i,each in enumerate(list):
        image = load_image(f"pic/{each}")
        data = torch.from_numpy(image)
        data = data.to(torch.device("cpu"))
        output = model(data)  # 获取特征
        output = output.data.cpu().numpy()
        # print(output.shape)

        # 获取不重复图片 并分组
        fe_1 = output[0]
        fe_2 = output[1]
        # print("this",cnt)
        # print(fe_1.shape,fe_2.shape)
        feature = np.hstack((fe_1, fe_2))
        # print(feature.shape)

        person_dict[each] = feature
    return person_dict
'''
def get_ouyannanafeature(model):

    image = load_image("inference/ouyanana.jpg")
    #print(image.shape)

    data = torch.from_numpy(image)
    data = data.to(torch.device("cpu"))
    output = model(data)  # 获取特征
    output = output.data.cpu().numpy()
    #print(output.shape)

    # 获取不重复图片 并分组
    fe_1 = output[0]
    fe_2 = output[1]
    # print("this",cnt)
    # print(fe_1.shape,fe_2.shape)
    feature = np.hstack((fe_1, fe_2))
    #print(feature.shape)

    person_dict = {}
    person_dict["ouyannana"] = feature

    return person_dict
'''
def cv2ImgAddText(img, text, left, top, textColor=(0, 0, 255), textSize=40):
    if (isinstance(img, np.ndarray)):  # 判断是否OpenCV图片类型
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    # 创建一个可以在给定图像上绘图的对象
    draw = ImageDraw.Draw(img)
    # 字体的格式
    fontStyle = ImageFont.truetype(
        "font/simsun.ttc", textSize, encoding="utf-8")
    # 绘制文本
    draw.text((left, top), text, textColor, font=fontStyle)
    # 转换回OpenCV格式
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

def detect(save_img=False):
    out, source, weights, view_img, save_txt, imgsz = \
        opt.output, opt.source, opt.weights, opt.view_img, opt.save_txt, opt.img_size # 加载配置信息

    webcam = source == '0' or source.startswith('rtsp') or source.startswith('http') or source.endswith('.txt') # 判断测试的资源类型

    # Initialize
    device = torch_utils.select_device(opt.device)
    dir = "pic"


    # 创建输出文件夹
    if os.path.exists(out):
        shutil.rmtree(out)  # delete output folder
    os.makedirs(out)  # make new output folder
    # gpu是否支持半精度 提高性能
    half = device.type != 'cpu'  # half precision only supported on CUDA

    # Load model

    model = torch.load(weights, map_location=torch.device('cpu'))['model'].float()  # load to FP32

    model.to(device).eval()

    arcface_model = resnet_face18(False)

    arcface_model = DataParallel(arcface_model)
    # load_model(model, opt.test_model_path)
    arcface_model.load_state_dict(torch.load('weights/resnet18_110.pth',map_location=torch.device('cpu')), strict=False)
    arcface_model.to(torch.device("cpu")).eval()

    pred_model = AntiSpoofPredict(0)

    if half:
        model.half()  # to FP16

    features = get_featuresdict(arcface_model, dir)#结合ArcFace

    vid_path, vid_writer = None, None
    if webcam:
        view_img = True
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz)
    else:
        # 图片和视频的加载
        save_img = True
        dataset = LoadImages(source, img_size=imgsz)
    view_img = True
    # Get names and colors 获得框框的类别名和颜色
    names = model.names if hasattr(model, 'names') else model.modules.names
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in range(len(names))]

    # Run inference 推理过程
    t0 = time.time()

    img = torch.zeros((1, 3, imgsz, imgsz), device=device)  # init img
    _ = model(img.half() if half else img) if device.type != 'cpu' else None  # run once 模拟启动

    count_none_nums = 0

    # 数据预处理
    for path, img, im0s, vid_cap in dataset:
        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)
        # Inference
        t1 = torch_utils.time_synchronized()
        pred = model(img, augment=opt.augment)[0]

        # Apply NMS 执行nms筛选boxes
        pred = non_max_suppression(pred, opt.conf_thres, opt.iou_thres, classes=opt.classes, agnostic=opt.agnostic_nms)
        t2 = torch_utils.time_synchronized()

        # Process detections
        for i, det in enumerate(pred):  # detections per image
            if webcam:  # batch_size >= 1
                p, s, im0 = path[i], '%g: ' % i, im0s[i].copy()
            else:
                p, s, im0 = path, '', im0s

            save_path = str(Path(out) / Path(p).name)
            s += '%gx%g ' % img.shape[2:]  # print string

            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  #  normalization gain whwh


            if det is not None and len(det): # 假如预测到有目标（盒子存在）
                # Rescale boxes from img_size to im0 size 还原盒子在原图上的位置
                det[:, :4] = scale_coords(img.shape[2:], det[:, :4], im0.shape).round()

                # Print results 打印box的结果信息
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += '%g %ss, ' % (n, names[int(c)])  # add to string

                # Write results
                for *xyxy, conf, cls in det:  # x1 y1 x2 y2 cls class
                    prediction = np.zeros((1, 3))

                    face_img = im0[int(xyxy[1]):int(xyxy[3]), int(xyxy[0]):int(xyxy[2])]  # 裁剪侦测到的人脸部分
                    rf_img = cv2.resize(face_img, (80, 80))
                    face_img = cv2.resize(face_img, (128, 128))  # 缩放至128*128
                    face_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
                    face_img = np.dstack((face_img, np.fliplr(face_img)))

                    face_img = face_img.transpose((2, 0, 1))
                    face_img = face_img[:, np.newaxis, :, :]

                    face_img = face_img.astype(np.float32, copy=False)
                    face_img -= 127.5
                    face_img /= 127.5

                    face_data = torch.from_numpy(face_img)
                    face_data = face_data.to(torch.device("cpu"))
                    # 获取特征
                    _output = arcface_model(face_data)
                    _output = _output.data.cpu().numpy()

                    fe_1 = _output[0]
                    fe_2 = _output[1]

                    _feature = np.hstack((fe_1, fe_2))

                    # label = '%s %.2f' % (names[int(cls)], conf)
                    label = "none"
                    list = features.keys()
                    max_f = 0
                    t = 0
                    # 比较数据库中每一张图片的余弦相似度
                    for i, each in enumerate(list):
                        t = cosin_metric(features[each], _feature)
                        print(each,t)
                        if t > max_f:
                            max_f = t
                            max_n = each
                        #print(max_n,max_f)
                        if (max_f>0.5):
                            label = max_n[:-4]
                    if label=="none":
                        count_none_nums +=1
                        new_name ="none_"+str(count_none_nums)+".jpg"
                        features[new_name]=_feature
                        print("none people nums:",count_none_nums)
                    if opt.open_rf:
                        # pred real or fake
                        for model_name in os.listdir("weights/anti_spoof_models"):
                            # print(model_test.predict(img, os.path.join(model_dir, model_name)))

                            prediction += pred_model.predict(rf_img, os.path.join("weights/anti_spoof_models", model_name))
                        rf_label = np.argmax(prediction)
                        value = prediction[0][rf_label] / 2
                        print(rf_label, value)
                        if rf_label == 1 and value > 0.90:
                            label += "_real"
                        else:
                            label += "_fake"
                    plot_one_box(xyxy, im0, label=label, color=colors[int(cls)], line_thickness=4)
                    #im0 = cv2ImgAddText(im0, 'Warning： 可疑人员' + str(count_none_nums) + '人！', 10, 65, (255, 0, 0), 80)
                    #cv2.putText(im0, 'null people: '+str(count_none_nums), (0, 50), cv2.FONT_HERSHEY_COMPLEX, 2, (0, 0, 255), 5)
            # Print time (inference + NMS)
            print('%sDone. (%.3fs)' % (s, t2 - t1)) # 输出执行时间

            # Stream results # 显示输出
            # if view_img:
            #     cv2.imshow(p, im0)
            #     if cv2.waitKey(1) == ord('q'):  # q to quit
            #         raise StopIteration

            # Save results (image with detections)
            if save_img: # 保存图片or视频
                if dataset.mode == 'images':
                    cv2.imwrite(save_path, im0)
                else:
                    if vid_path != save_path:  # new video
                        vid_path = save_path
                        if isinstance(vid_writer, cv2.VideoWriter):
                            vid_writer.release()  # release previous video writer

                        fps = vid_cap.get(cv2.CAP_PROP_FPS)
                        w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*opt.fourcc), fps, (w, h))
                    vid_writer.write(im0)

    if save_txt or save_img:
        print('Results saved to %s' % os.getcwd() + os.sep + out)
        if platform == 'darwin':  # MacOS
            os.system('open ' + save_path)

    print('Done. (%.3fs)' % (time.time() - t0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', type=str, default='weights/best.pt', help='model.pt path')
    parser.add_argument('--source', type=str, default='inference/images', help='source')  # file/folder, 0 for webcam
    parser.add_argument('--output', type=str, default='inference/output', help='output folder')  # output folder
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.4, help='object confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.5, help='IOU threshold for NMS')
    parser.add_argument('--fourcc', type=str, default='mp4v', help='output video codec (verify ffmpeg support)')
    parser.add_argument('--device', default='', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--view-img', action='store_true', help='display results')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--classes', nargs='+', type=int, help='filter by class')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--open_rf', default=1, help='if open real/fake 1 0 ')
    opt = parser.parse_args()
    opt.img_size = check_img_size(opt.img_size)
    print(opt)


    with torch.no_grad():
        detect()
