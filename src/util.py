import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
import numpy as np
np.set_printoptions(threshold=np.inf)
import os, cv2, shutil
from scipy.io import loadmat
from PIL import Image, ImageDraw
from glob import glob
from imgaug import augmenters as iaa
import imgaug as ia
from config import Config
from PIL import ImageEnhance

ROOT_DIR = os.getcwd()
if ROOT_DIR.endswith('src'):
    ROOT_DIR = os.path.dirname(ROOT_DIR)

WEIGHT_DIR = os.path.join(ROOT_DIR, 'model_weights')
CRC_DIR = os.path.join(ROOT_DIR, 'CRCHistoPhenotypes_2016_04_28')
DETECT_DIR = os.path.join(CRC_DIR, 'Detection')
CLS_DIR = os.path.join(CRC_DIR, 'Classification')


def _isArrayLike(obj):
    """
    check if this is array like object.
    """
    return hasattr(obj, '__iter__') and hasattr(obj, '__len__')


def set_num_step_and_aug():
    """
    Because the size of image is big and it would store in computation graph for doing back propagation,
    we set different augmentation number and training step depends on which struture we are using.
    :return:
    """
    NUM_TO_AUG, TRAIN_STEP_PER_EPOCH = 0, 0
    if Config.backbone == 'resnet101':
        NUM_TO_AUG = 6
        TRAIN_STEP_PER_EPOCH = 32
    elif Config.backbone == 'resnet152':
        NUM_TO_AUG = 3
        TRAIN_STEP_PER_EPOCH = 50
    elif Config.backbone == 'resnet50' or Config.backbone == 'fcn36_fpn':
        NUM_TO_AUG = 2
        TRAIN_STEP_PER_EPOCH = 50
    elif Config.backbone == 'resnet50_encoder_shallow' or Config.backbone == 'resnet50_encoder_deep':
        NUM_TO_AUG = 3
        TRAIN_STEP_PER_EPOCH = 80

    return NUM_TO_AUG, TRAIN_STEP_PER_EPOCH


def set_gpu():
    """
    Set gpu config if gpu is available
    """
    if Config.gpu_count == 1:
        os.environ["CUDA_VISIBLE_DEVICES"] = Config.gpu1
    elif Config.gpu_count == 2:
        os.environ["CUDA_VISIBLE_DEVICES"] = Config.gpu1 + ', ' + Config.gpu2
    elif Config.gpu_count == 3:
        os.environ["CUDA_VISIBLE_DEVICES"] = Config.gpu1 + ', ' + Config.gpu2 + ', ' + Config.gpu3
    elif Config.gpu_count == 4:
        os.environ["CUDA_VISIBLE_DEVICES"] = Config.gpu1 + ', ' + Config.gpu2 + ', ' + Config.gpu3 + ', ' + Config.gpu4


def lr_scheduler(epoch):
    """
    use this for learning rate during training
    :param epoch:
    :return:
    """
    lr = 0.01
    if epoch < 100 and epoch != 0:
        lr = lr - 0.0001
    if epoch % 10 == 0:
        print('Current learning rate is :{}'.format(lr))
    if epoch == 100:
        lr = 0.001
        print('Learning rate is modified after 100 epoch {}'.format(lr))
    if epoch == 150:
        lr = 0.0001
    if epoch == 200:
        lr = 0.00001
    if epoch == 250:
        lr = 0.000001
    return lr


def aug_on_fly(img, det_mask, cls_mask):
    """Do augmentation with different combination on each training batch
    """
    def image_basic_augmentation(image, masks, ratio_operations=0.9):
        # without additional operations
        # according to the paper, operations such as shearing, fliping horizontal/vertical,
        # rotating, zooming and channel shifting will be apply
        sometimes = lambda aug: iaa.Sometimes(ratio_operations, aug)
        hor_flip_angle = np.random.uniform(0, 1)
        ver_flip_angle = np.random.uniform(0, 1)
        seq = iaa.Sequential([
            sometimes(
                iaa.SomeOf((0, 5), [
                iaa.Fliplr(hor_flip_angle),
                iaa.Flipud(ver_flip_angle),
                iaa.Affine(shear=(-16, 16)),
                iaa.Affine(scale={'x': (1, 1.6), 'y': (1, 1.6)}),
                iaa.PerspectiveTransform(scale=(0.01, 0.1))
            ]))
        ])
        det_mask, cls_mask = masks[0], masks[1]
        seq_to_deterministic = seq.to_deterministic()
        aug_img = seq_to_deterministic.augment_images(image)
        aug_det_mask = seq_to_deterministic.augment_images(det_mask)
        aug_cls_mask = seq_to_deterministic.augment_images(cls_mask)
        return aug_img, aug_det_mask, aug_cls_mask

    aug_image, aug_det_mask, aug_cls_mask = image_basic_augmentation(image=img, masks=[det_mask, cls_mask])
    return aug_image, aug_det_mask, aug_cls_mask

def heavy_aug_on_fly(img, det_mask):
    """Do augmentation with different combination on each training batch
    """

    def image_heavy_augmentation(image, det_masks, ratio_operations=0.6):
        # according to the paper, operations such as shearing, fliping horizontal/vertical,
        # rotating, zooming and channel shifting will be apply
        sometimes = lambda aug: iaa.Sometimes(ratio_operations, aug)
        edge_detect_sometime = lambda aug: iaa.Sometimes(0.1, aug)
        elasitic_sometime = lambda aug:iaa.Sometimes(0.2, aug)
        add_gauss_noise = lambda aug: iaa.Sometimes(0.15, aug)
        hor_flip_angle = np.random.uniform(0, 1)
        ver_flip_angle = np.random.uniform(0, 1)
        seq = iaa.Sequential([
            iaa.SomeOf((0, 5), [
                iaa.Fliplr(hor_flip_angle),
                iaa.Flipud(ver_flip_angle),
                iaa.Affine(shear=(-16, 16)),
                iaa.Affine(scale={'x': (1, 1.6), 'y': (1, 1.6)}),
                iaa.PerspectiveTransform(scale=(0.01, 0.1)),

                # These are additional augmentation.
                #iaa.ContrastNormalization((0.75, 1.5))

            ])])
            #elasitic_sometime(
             #   iaa.ElasticTransformation(alpha=(0.5, 3.5), sigma=0.25), random_order=True])
        """
                    edge_detect_sometime(iaa.OneOf([
                        iaa.EdgeDetect(alpha=(0, 0.7)),
                        iaa.DirectedEdgeDetect(alpha=(0,0.7), direction=(0.0, 1.0)
                                               )
                    ])),
                    add_gauss_noise(iaa.AdditiveGaussianNoise(loc=0,
                                                              scale=(0.0, 0.05*255),
                                                              per_channel=0.5)
                                    ),
                    iaa.Sometimes(0.3,
                                  iaa.GaussianBlur(sigma=(0, 0.5))
                                  ),
                    elasitic_sometime(
                        iaa.ElasticTransformation(alpha=(0.5, 3.5), sigma=0.25)
                    """
        seq_to_deterministic = seq.to_deterministic()
        aug_img = seq_to_deterministic.augment_images(image)
        aug_det_mask = seq_to_deterministic.augment_images(det_masks)
        return aug_img, aug_det_mask

    aug_image, aug_det_mask = image_heavy_augmentation(image=img, det_masks=det_mask)
    return aug_image, aug_det_mask


def train_test_split(data_path, notation_type, new_folder = 'cls_and_det', 
                     test_sample = 20, valid_sample = 10):
    """
    randomly split data into train, test and validation set. pre-defined number was based
    on sfcn-opi paper
    :param data_path: main path for the original data. ie: ../CRCHistoPhenotypes_2016_04_28
    :param new_folder: new folder to store train, test, and validation files
    :param train_sample: number of train sample
    :param test_sample: number of test sample
    :param valid_sample: number of validation sample
    """
    if notation_type == 'ellipse':
        new_folder_path = os.path.join(data_path, new_folder + '_ellipse')
    elif notation_type == 'point':
        new_folder_path = os.path.join(data_path, new_folder + '_point')
    else:
        raise Exception('notation type needs to be either ellipse or point')
    
    train_new_folder = os.path.join(new_folder_path, 'train')
    test_new_folder = os.path.join(new_folder_path, 'test')
    valid_new_folder = os.path.join(new_folder_path, 'validation')
    check_folder_list = [new_folder_path, train_new_folder, test_new_folder, valid_new_folder]
    check_directory(check_folder_list)

    detection_folder = os.path.join(data_path, 'Detection')
    classification_folder = os.path.join(data_path, 'Classification')

    # Wrong if number of images in detection and classification folder are not match.
    #assert len(os.listdir(detection_folder)) == len(os.listdir(classification_folder))
    length = len(os.listdir(detection_folder))

    image_order = np.arange(1, length+1)
    np.random.shuffle(image_order)

    for i, order in enumerate(image_order):
        img_folder = os.path.join(classification_folder, 'img{}'.format(order))
        det_mat = os.path.join(detection_folder, 'img{}'.format(order), 'img{}_detection.mat'.format(order))
        if i < test_sample:
            shutil.move(img_folder, test_new_folder)
            new = os.path.join(test_new_folder, 'img{}'.format(order))
            shutil.move(det_mat, new)
        elif i < test_sample + valid_sample:
            shutil.move(img_folder, valid_new_folder)
            new = os.path.join(valid_new_folder, 'img{}'.format(order))
            shutil.move(det_mat, new)
        else:
            shutil.move(img_folder, train_new_folder)
            new = os.path.join(train_new_folder, 'img{}'.format(order))
            shutil.move(det_mat, new)
        mats = glob('{}/*.mat'.format(new), recursive=True)
        mat_list = []
        
        for mat in mats:
            store_name = mat.split('.')[0]
            mat_content = loadmat(mat)
            img = Image.open(os.path.join(new, 'img{}.bmp'.format(order)))
            img.save(os.path.join(new, 'img{}_original.bmp'.format(order)))
            
            if 'detection' in store_name:
                mask = _create_binary_masks_ellipse(mat_content, notation_type=notation_type, usage='Detection', colors=1)
                mask.save('{}.bmp'.format(store_name))
                verify_img = _drawdots_on_origin_image(mat_content, notation_type=notation_type,usage='Detection', img = img)
                verify_img.save('{}/img{}_verify_det.bmp'.format(new, order))
            elif 'detection' not in store_name:
                mat_list.append(mat_content)
        #if order == 1:
         #   print(mat_list)
        cls_mask = _create_binary_masks_ellipse(mat_list, notation_type=notation_type, usage='Classification')
        cls_mask.save('{}/img{}_classification.bmp'.format(new, order))
        verify_img = _drawdots_on_origin_image(mat_list, usage='Classification', notation_type=notation_type, img=img)
        verify_img.save('{}/img{}_verify_cls.bmp'.format(new, order))

    #_reorder_image_files(new_folder_path)



def _reorder_image_files(datapath, files= ['train', 'test', 'validation']):
    for file in files:
        sub_path = os.path.join(datapath, file)
        for i, img_folder in enumerate(os.listdir(sub_path)):
            new_img_folder = os.path.join(sub_path, 'img{}'.format(i + 1))
            shutil.move(os.path.join(sub_path, img_folder), new_img_folder)
            dir = [os.path.join(new_img_folder, img_file) for img_file in os.listdir(new_img_folder)]
            for d in dir:
                print('this is d: ',d)
                #pattern = re.split('img[\d]+', )
                #match = pattern.match(d)
               # print('match: ', pattern)
                start = d.find('/img\d_')
                new_file = os.path.join(img_folder, 'img{}'.format(i + 1), d[start:])
                os.rename(d, new_file)


def check_directory(file_path):
    """
    make new file on path if file is not already exist.
    :param file_path: file_path can be list of files to create.
    """
    if _isArrayLike(file_path):
        for file in file_path:
            if not os.path.exists(file):
                os.makedirs(file)
    else:
        if not os.path.exists(file_path):
            os.makedirs(file_path)


def check_cv2_imwrite(file_path, file):
    if not os.path.exists(file_path):
        cv2.imwrite(file_path, file)


def _draw_points(dots, img, color, notation_type, radius = 3):
    if dots is not None:
        canvas = ImageDraw.Draw(img)
        if notation_type == 'point':
            for i, dot in enumerate(dots):
                canvas.point(dot, fill=color)
        elif notation_type == 'ellipse':
            for i in range(len(dots)):
                x0 = dots[i, 0] - radius
                y0 = dots[i, 1] - radius
                x1 = dots[i, 0] + radius
                y1 = dots[i, 1] + radius
                canvas.ellipse((x0, y0, x1, y1), fill=color)


def _create_binary_masks_ellipse(mats, usage, notation_type, colors):
    """
    create binary mask using loaded data
    :param mats: points, mat format
    :param usage: Detection or Classfifcation
    :param notation_type: For now, either ellipse or point
    :return: mask
    """
    mask = Image.new('L', (500, 500), 0)
    if usage == 'Classification':
        for i, mat in enumerate(mats):
            mat_content = mat['detection']
            if notation_type == 'ellipse':
                _draw_points(mat_content, mask, notation_type=notation_type, color=colors)
            elif notation_type == 'point':
                _draw_points(mat_content, mask, color=colors, notation_type=notation_type)
    elif usage == 'Detection':
        mat_content = mats['detection']
        if notation_type == 'ellipse':
            _draw_points(mat_content, mask, color=1, notation_type=notation_type)
        elif notation_type == 'point':
            _draw_points(mat_content, mask, color=1, notation_type=notation_type)
    return mask


def _drawdots_on_origin_image(mats, usage, img, notation_type, color = ['yellow', 'green', 'blue', 'red']):
    """
    For visualizatoin purpose, draw different color on original image.
    :param mats:
    :param usage: Detection or Classfifcation
    :param img: original image
    :param color: color list for each category
    :return: dotted image
    """
    if usage == 'Classification':
        for i, mat in enumerate(mats):
            mat_content = mat['detection']
            _draw_points(mat_content, img, color[i], notation_type = notation_type)
    elif usage == 'Detection':
        mat_content = mats['detection']
        _draw_points(mat_content, img, color[0], notation_type=notation_type)
    return img


def create_binary_masks(mat):
    polygon = [(point[0], point[1]) for point in mat]
    #print(polygon)
    mask = Image.new('L', (500, 500), 0)
    ImageDraw.Draw(mask).polygon(polygon, outline=1, fill=1)
    return mask



def img_test(p, i, type):
    """
    visiualize certain image by showing all corresponding images.
    :param i: which image
    :param type: train, test or validation
    """
    img = Image.open(os.path.join(p, 'cls_and_det', type, 'img{}'.format(i), 'img{}.bmp'.format(i)))
    imgd = Image.open(
       os.path.join(p, 'cls_and_det', type, 'img{}'.format(i), 'img{}_detection.bmp'.format(i)))
    imgc = Image.open(
       os.path.join(p, 'cls_and_det', type, 'img{}'.format(i), 'img{}_classification.bmp'.format(i)))
    imgv = Image.open(
       os.path.join(p, 'cls_and_det', type, 'img{}'.format(i), 'img{}_verifiy_classification.bmp'.format(i)))
    imgz = Image.open(
       os.path.join(p, 'cls_and_det', type, 'img{}'.format(i), 'img{}_verifiy_detection.bmp'.format(i)))
    contrast = ImageEnhance.Contrast(imgd)
    contrast2 = ImageEnhance.Contrast(imgc)
    img.show(img)
    imgv.show(imgv)
    imgz.show(imgz)
    contrast.enhance(20).show(imgd)
    contrast2.enhance(20).show(imgc)



def mask_to_corrdinates(mask):
    a = np.where(mask == 1)
    x = []
    for i, num in enumerate(a[0]):
        c = (a[1][i], num)
        x.append(c)
    print(x)


def _create_cls_mask(parent_folder, mats):
    """
    create binary mask using loaded data
    :param mats: points, mat format
    :param usage: Detection or Classfifcation
    :param notation_type: For now, either ellipse or point
    :return: mask
    """
    mask = Image.new('L', (500, 500), 0)
    #mats is a list of mat path contains four mats path
    for i, mat in enumerate(mats):
        mat_path = os.path.join(parent_folder, mat)
        mat_content = loadmat(mat_path)['detection']
        if 'epithelial.mat' in mat:
            draw_points(mat_content, mask, 1)
        if 'fibroblast.mat' in img_file:
            draw_points(mat_content, mask, 2)
        if 'inflammatory.mat' in img_file:
            draw_points(mat_content, mask, 3)
        if 'others.mat' in img_file:
            draw_points(mat_content, mask, 4)
    return mask


def draw_points(dots, img, color, radius=3):
    if dots is not None:
        canvas = ImageDraw.Draw(img)
        for i in range(len(dots)):
            x0 = dots[i, 0] - radius
            y0 = dots[i, 1] - radius
            x1 = dots[i, 0] + radius
            y1 = dots[i, 1] + radius
            canvas.ellipse((x0, y0, x1, y1), fill=color)


if __name__ == '__main__':
    import keras.backend as K

    for file in os.listdir(CLS_DIR):
        file_path = os.path.join(CLS_DIR, file)
        mats_list = []
        #print(file)
        for img_file in os.listdir(file_path):
            if '.mat' in img_file:
                mats_list.append(os.path.join(file_path, img_file))
        image_mask = _create_cls_mask(file_path, mats_list)
        if '54' in file:
            print(file)
        image_mask.save(os.path.join(file_path, str(file)+ '_classification.bmp'))

    train_cls_dir = os.path.join(CRC_DIR, 'cls_and_det', 'train')
    test_cls_dir = os.path.join(CRC_DIR, 'cls_and_det', 'test')
    valid_cls_dir = os.path.join(CRC_DIR, 'cls_and_det', 'validation')
    for files in os.listdir(train_cls_dir):
        cls_dir_file = os.path.join(train_cls_dir, files)
        CLS_DIR_FILE = os.path.join(CLS_DIR, files)
        for img_file in os.listdir(cls_dir_file):
            cls_img_file = os.path.join(cls_dir_file, str(files)+'_classification.bmp')
            CLS_IMG_FILE = os.path.join(CLS_DIR_FILE, str(files)+'_classification.bmp')
            if os.path.exists(cls_img_file):
                os.remove(cls_img_file)
            shutil.move(CLS_IMG_FILE, cls_img_file)
    for files in os.listdir(test_cls_dir):
        cls_dir_file = os.path.join(test_cls_dir, files)
        CLS_DIR_FILE = os.path.join(CLS_DIR, files)
        for img_file in os.listdir(cls_dir_file):
            cls_img_file = os.path.join(cls_dir_file, str(files) + '_classification.bmp')
            CLS_IMG_FILE = os.path.join(CLS_DIR_FILE, str(files) + '_classification.bmp')
            if os.path.exists(cls_img_file):
                os.remove(cls_img_file)
            shutil.move(CLS_IMG_FILE, cls_img_file)

    for files in os.listdir(valid_cls_dir):
        cls_dir_file = os.path.join(valid_cls_dir, files)
        CLS_DIR_FILE = os.path.join(CLS_DIR, files)
        for img_file in os.listdir(cls_dir_file):
            cls_img_file = os.path.join(cls_dir_file, str(files) + '_classification.bmp')
            CLS_IMG_FILE = os.path.join(CLS_DIR_FILE, str(files) + '_classification.bmp')
            if os.path.exists(cls_img_file):
                os.remove(cls_img_file)
            shutil.move(CLS_IMG_FILE, cls_img_file)
        """
    p = '/home/yichen/Desktop/sfcn-opi-yichen/CRCHistoPhenotypes_2016_04_28'
    from PIL import Image, ImageEnhance
    load_mask = Image.open('/home/yichen/Desktop/sfcn-opi-yichen/CRCHistoPhenotypes_2016_04_28/cls_and_det/train/img1/img1_detection.bmp')
    contrast = ImageEnhance.Contrast(load_mask)
    contrast.enhance(200).show(load_mask)
    maskt = cv2.imread('/home/yichen/Desktop/sfcn-opi-yichen/CRCHistoPhenotypes_2016_04_28/cls_and_det/train/img1/img1_detection.bmp', 0)
    mask_to_corrdinates(maskt)
    mat = loadmat('/home/yichen/Desktop/sfcn-opi-yichen/CRCHistoPhenotypes_2016_04_28/cls_and_det/train/img1/img1_detection.mat')['detection']
    print(np.sort(mat, axis=-1))

    
    p = '/home/yichen/Desktop/sfcn-opi-yichen/CRCHistoPhenotypes_2016_04_28'
    print(os.path.abspath('CRCHistoPhenotypes_2016_04_28'))
    #_reorder_image_files('/home/yichen/Desktop/sfcn-opi-yichen/CRCHistoPhenotypes_2016_04_28/cls_and_det')
    train_test_split(p, notation_type='point')
    from PIL import Image, ImageEnhance
    i = 1
    #img_test(i, 'test')"""