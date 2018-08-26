from encoder_decoder_object_det import Detnet
import scipy.misc as misc
import numpy as np
import matplotlib.pyplot as plt
import os
from config import Config
#from metric import non_max_suppression, get_metrics
import scipy.io as sio
import cv2
from encoder_append import *
from eval import mymetrics

weight_path = 'multi_fcn36_loss:fd_det:0.13_fkg:0.5_bkg:0.5_lr:0.01_train.h5'
ROOT_DIR = os.getcwd()
if ROOT_DIR.endswith('src'):
    ROOT_DIR = os.path.dirname(ROOT_DIR)

WEIGHT_DIR = os.path.join(ROOT_DIR, 'model_weights')
IMG_DIR = os.path.join(ROOT_DIR, 'CRCHistoPhenotypes_2016_04_28', 'cls_and_det', 'test')
#IMG_DIR = os.path.join(ROOT_DIR, 'crop_cls_and_det', 'test')
epsilon = 1e-6

def non_max_suppression(img, overlap_thresh=0.3, max_boxes=1200, r=8, prob_thresh=0.6):  # net_4_w6_di2.pkl
    # over=0.2, max=1200,r=7,prob=0.85 --> P:0.837 R:0.894 F:0.865
    # over=0.3, max=1200,r=8,prob=0.85 --> P:0.824 R:0.920 F:0.869
    x1s = []
    y1s = []
    x2s = []
    y2s = []
    probs = []
    for i in range(img.shape[0]):
        for j in range(img.shape[1]):
            if img[i, j] < prob_thresh:
                img[i, j] = 0
            else:
                x1 = max(j - r, 0)
                y1 = max(i - r, 0)
                x2 = min(j + r, img.shape[1] - 1)
                y2 = min(i + r, img.shape[0] - 1)
                x1s.append(x1)
                y1s.append(y1)
                x2s.append(x2)
                y2s.append(y2)
                probs.append(img[i, j])
    x1s = np.array(x1s)
    y1s = np.array(y1s)
    x2s = np.array(x2s)
    y2s = np.array(y2s)
    # print(x1s.shape)
    boxes = np.concatenate((x1s.reshape((x1s.shape[0], 1)), y1s.reshape((y1s.shape[0], 1)), x2s.reshape((x2s.shape[0], 1)),
                            y2s.reshape((y2s.shape[0], 1))), axis=1)
    # print(boxes.shape)
    probs = np.array(probs)
    pick = []
    area = (x2s - x1s) * (y2s - y1s)
    indexes = np.argsort([i for i in probs])

    while len(indexes) > 0:
        last = len(indexes) - 1
        i = indexes[last]
        pick.append(i)

        xx1_int = np.maximum(x1s[i], x1s[indexes[:last]])
        yy1_int = np.maximum(y1s[i], y1s[indexes[:last]])
        xx2_int = np.minimum(x2s[i], x2s[indexes[:last]])
        yy2_int = np.minimum(y2s[i], y2s[indexes[:last]])

        ww_int = np.maximum(0, xx2_int - xx1_int)
        hh_int = np.maximum(0, yy2_int - yy1_int)

        area_int = ww_int * hh_int
        # find the union
        area_union = area[i] + area[indexes[:last]] - area_int

        # compute the ratio of overlap
        overlap = area_int / (area_union + 1e-6)

        indexes = np.delete(indexes, np.concatenate(([last], np.where(overlap > overlap_thresh)[0])))

        if len(pick) >= max_boxes:
            break
            # return only the bounding boxes that were picked using the integer data type
    boxes = boxes[pick]
    # print(boxes.shape)
    return boxes


def get_metrics(gt, pred, r=6):
    # calculate precise, recall and f1 score
    gt = np.array(gt).astype('int')
    if pred == []:
        if gt.shape[0] == 0:
            return 1, 1, 1, 0
        else:
            return 0, 0, 0, 0


    pred = np.array(pred).astype('int')

    temp = np.concatenate([gt, pred])

    if temp.shape[0] != 0:
        x_max = np.max(temp[:, 0]) + 1
        y_max = np.max(temp[:, 1]) + 1

        #gt_map = np.zeros((y_max, x_max), dtype='int')
        gt_map = np.zeros((500, 500)).astype(np.int8)
        for i in range(gt.shape[0]):
            x = gt[i, 0]
            y = gt[i, 1]
            x1 = max(0, x - r)
            y1 = max(0, y - r)
            x2 = min(x_max, x + r)
            y2 = min(y_max, y + r)
            # gt_map[y1:y2,x1:x2] = 1
            cv2.circle(gt_map, (x, y), r, 1, -1)
        #plt.imshow(gt_map)
        #plt.show()

        #pred_map = np.zeros((y_max, x_max), dtype='int')
        pred_map = np.zeros((500,500),dtype='int')
        for i in range(pred.shape[0]):
            x = pred[i, 0]
            y = pred[i, 1]
            pred_map[y, x] = 1

        result_map = gt_map * pred_map
        tp = result_map.sum()

        precision = min(tp / (pred.shape[0] + epsilon),1)
        recall = min(tp / (gt.shape[0] + epsilon),1)
        f1_score = 2 * (precision * recall / (precision + recall + epsilon))
        gt_num = gt.shape[0]
        pred_num = pred.shape[0]
        return precision, recall, f1_score, tp, gt_num, pred_num



def eval_single_img(model, img_dir, print_img=True,
                    prob_threshold=None, print_single_result=True):
    image_path = os.path.join(IMG_DIR, img_dir, img_dir+ '.bmp')
    img = misc.imread(image_path)
    img = misc.imresize(img, (256, 256))#, interp='nearest')
    img = img - 128.0
    img = img / 128.0
    img = img.reshape((1, img.shape[0], img.shape[1], img.shape[2]))
    output = model.predict(img)[0]
    output = output[:, :, 1]
    #cropped_img1 = img[0: 256, 0: 256, :]  # 1, 3
    #cropped_img2 = img[256: 512, 0: 256, :]  # 2, 4
    #cropped_img3 = img[0: 256, 256: 512, :]
    #cropped_img4 = img[256: 512, 256: 512, :]
    #print('crop shape: ', cropped_img1.shape)
    #plt.imshow(cropped_img1)
    #plt.colorbar()
    #plt.show()
    def _predic_crop_image(img, print_img=print_img):
        img = img.reshape((1, img.shape[0], img.shape[1], img.shape[2]))
        output = model.predict(img)[0]
        output = output[:, :, 1]
        return output

    #crop_output1 = _predic_crop_image(cropped_img1)
    #crop_output2 = _predic_crop_image(cropped_img2)
    #crop_output3 = _predic_crop_image(cropped_img3)
    #crop_output4 = _predic_crop_image(cropped_img4)

   # output_up = np.concatenate((crop_output1, crop_output3), axis=1)
   # output_down = np.concatenate((crop_output2, crop_output4), axis=1)
    #output = np.concatenate((output_up, output_down), axis=0)

    if print_img:
        plt.imshow(output)
        plt.title(weight_path)
        plt.colorbar()
        plt.show()
    #print(output.shape)

    p, r, f1, tp, gt, pred2 = score_single_img(output, img_dir=img_dir, prob_threshold=prob_threshold, print_single_result=print_single_result)
    return p, r, f1, tp, gt, pred2


def score_single_img(input, img_dir, prob_threshold=None, print_single_result=True):
    input = misc.imresize(input, (500, 500))
    input = input / 255.
    boxes = non_max_suppression(input, prob_thresh=prob_threshold)

    num_of_nuclei = boxes.shape[0]

    mat_path = os.path.join(IMG_DIR, img_dir, img_dir + '_detection.mat')
    #print(mat_path)
    gt = sio.loadmat(mat_path)['detection']
    outputbase = cv2.imread(os.path.join(IMG_DIR, img_dir, img_dir + '.bmp'))
    if print_single_result:
        print('----------------------------------')
        print('This is {}'.format(img_dir))
        print('detected: {}, ground truth: {}'.format(num_of_nuclei, gt.shape[0]))
    pred = []
    for i in range(boxes.shape[0]):
        x1 = boxes[i, 0]
        y1 = boxes[i, 1]
        x2 = boxes[i, 2]
        y2 = boxes[i, 3]
        cx = int(x1 + (x2 - x1) / 2)
        cy = int(y1 + (y2 - y1) / 2)
        # cv2.rectangle(outputbase,(x1, y1), (x2, y2),(255,0,0), 1)
        cv2.circle(outputbase, (cx, cy), 3, (255, 255, 0), -1)
        pred.append([cx, cy])
    p, r, f1, tp, aaa, bbb = get_metrics(gt, pred)
    return p, r, f1, tp, aaa, bbb


def eval_testset(model, prob_threshold=None, print_img=False, print_single_result=True):
    total_p, total_r, total_f1, total_tp = 0, 0, 0, 0
    tp_total_num, gt_total_num, pred_total_num = 0, 0, 0
    for img_dir in os.listdir(IMG_DIR):
        p, r, f1, tp, gt, pred = eval_single_img(model, img_dir, print_img=print_img,
                                       print_single_result=print_single_result,
                                       prob_threshold=prob_threshold)
        print('{} p: {}, r: {}, f1: {}, tp: {}'.format(img_dir, p, r, f1, tp))
        total_p += p
        total_r += r
        total_f1 += f1
        total_tp += tp

        tp_total_num += tp
        gt_total_num += gt
        pred_total_num += pred

    precision = tp_total_num/(pred_total_num + epsilon)
    recall = tp_total_num / (gt_total_num + epsilon)
    f1_score = 2 * (precision * recall) / (precision + recall + epsilon)
    print('Over points, the precision: {}, recall: {}, f1: {}'.format(precision, recall, f1_score))
    if prob_threshold is not None:
        print('The nms threshold is {}'.format(prob_threshold))
    print('Over test set, the average P: {}, R: {}, F1: {}, TP: {}'.format(total_p/20,total_r/20,total_f1/20, total_tp/20))
    return precision, recall, f1_score, total_p/20,total_r/20,total_f1/20, total_tp/20

def best_test():




def test_11(model):
    p, r, f1, tp, gt, pred= eval_single_img(model, 'img11', print_img=True,
                                   print_single_result=False,
                                   prob_threshold=0.8)
    print('Over test set, the average P: {}, R: {}, F1: {}, TP: {}'.format(p, r, f1, tp))


if __name__ == '__main__':
    #model = Fcn_det().fcn36_deconv_backbone()
    #model.load_weights(os.path.join(WEIGHT_DIR, weight_path))
    #test_11(model)
    import time
    #os.environ["CUDA_VISIBLE_DEVICES"] = str(Config.gpu1)
    start = time.time()
    #weight_path = 'focal_double_resnet50_loss:fd_det:0.1_fkg:2_bkg:2_lr:0.01_train.h5'
    imgdir = 'img' + str(2)
    model = Fcn_det().relufirst_fcn36_deconv_backbone()
    #eval_weights_testset(WEIGHT_DIR)
    for weight in os.listdir(WEIGHT_DIR):
        #if 'loss:fd_relufirst_det:' + str(Config.det_weight) in weight:
        print(weight)
        weightp = os.path.join(WEIGHT_DIR, weight)
        model.load_weights(weightp)
    #model.load_weights(os.path.join(WEIGHT_DIR, weight_path))
        prob_threshhold = [0.1, 0.15, 0.2, 0.22, 0.25, 0.28, 0.3, 0.32, 0.35, 0.38, 0.4,0.43, 0.45, 0.48, 0.5,0.52,0.55,0.58, 0.60,0.62,0.65, 0.7, 0.8, 0.9]
        #eval_single_img(model, imgdir)
        best_f1 = 0
        best_tf = 0
        best_p, best_r, best_tp, best_tr, best_tpp = 0, 0, 0, 0, 0
        for prob in prob_threshhold:
            print('The nms threshold is ', prob)
            p, r ,f1, tp, tr, tf, tpp = eval_testset(model, prob_threshold=prob, print_img=False, print_single_result=False)
            if best_f1 == 0:
                best_f1, best_tf = f1, tf
            else:
                if f1 > best_f1:
                    best_p, best_r, best_f1, best_tpp = p, r, f1, tpp
                if tf > best_tf:
                    best_tp, best_tr, best_tf = tp, tr, tf
        print('The best point score is p: {}, r: {}, f1: {}'.format(best_p, best_r, best_f1))
        print('The best average score is p: {}, r: {}, f1: {}'.format(best_tp, best_tr, best_tf))









'''
    print(p, r, f1)
    tp_num += tp
    gt_num += gt.shape[0]
    pred_num += np.array(pred).shape[0]
precision = tp_num / (pred_num + epsilon)
recall = tp_num / (gt_num + epsilon)
f1_score = 2 * (precision * recall / (precision + recall + epsilon))

print('Precision:', precision)
print('Recall:', recall)
print('F1 score:', f1_score)
'''

#model = Detnet(0.25).detnet_backbone()
#model.load_weights('../model_weights/focal_aug_elas_trans_smooth_4_bkg_1_train.h5')
#img = misc.imread('img90.bmp')

