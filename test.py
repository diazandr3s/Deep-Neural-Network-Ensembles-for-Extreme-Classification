from __future__ import print_function

import os
from torch.autograd import Variable
import torch.nn.functional as F
os.environ['CUDA_VISIBLE_DEVICES'] = '0'
from transform import *
from Utils import *
from cdimage import *
from torch.utils.data.sampler import RandomSampler
# --------------------------------------------------------

from net.resnet101 import ResNet101 as Net

use_cuda = True
IDENTIFIER = "resnet"
SEED = 123456
PROJECT_PATH = './project'
CDISCOUNT_HEIGHT = 180
CDISCOUNT_WIDTH = 180
CDISCOUNT_NUM_CLASSES = 5270

csv_dir = './data/'
root_dir = '../output/'
test_data_filename = 'test.csv'
validation_data_filename = 'validation.csv'

####################################################################################################
## common functions ##

def image_to_tensor_transform(image):
    tensor = pytorch_image_to_tensor_transform(image)
    tensor[ 0] = tensor[ 0] * (0.229 / 0.5) + (0.485 - 0.5) / 0.5
    tensor[ 1] = tensor[ 1] * (0.224 / 0.5) + (0.456 - 0.5) / 0.5
    tensor[ 2] = tensor[ 2] * (0.225 / 0.5) + (0.406 - 0.5) / 0.5
    return tensor

def valid_augment(image):

    image  = fix_center_crop(image, size=(160,160))
    tensor = image_to_tensor_transform(image)
    return tensor

def evaluate(net, test_loader):
    cnt = 0

    all_image_ids = np.array([])
    all_probs = np.array([]).reshape(0,5270)

    # for iter, (images, labels, indices) in enumerate(test_loader, 0):
    for iter, (images, image_ids) in enumerate(test_loader, 0):#remove indices for testing
        if cnt > 4:
            break;

        images = Variable(images.type(torch.FloatTensor)).cuda() if use_cuda else Variable(images.type(torch.FloatTensor))
        image_ids = np.array(image_ids)

        logits = net(images)
        probs  = F.softmax(logits)
        probs = probs.cpu().data.numpy() if use_cuda else probs.data.numpy()
        probs.astype(float)

        all_image_ids = np.concatenate((all_image_ids, image_ids), axis=0)
        all_probs = np.concatenate((all_probs, probs), axis=0)

        cnt = cnt + 1

    product_to_prediction_map = product_predict(all_image_ids, all_probs)

    return product_to_prediction_map

def write_test_result(path, product_to_prediction_map):
    with open(path, "a") as file:
        file.write("_id,category_id\n")

        for product_id, prediction in product_to_prediction_map.items():
            print(product_id)
            print(prediction)
            file.write(product_id + "," + prediction + "\n")



# main #################################################################
if __name__ == '__main__':
    print( '%s: calling main function ... ' % os.path.basename(__file__))

    initial_checkpoint = "../checkpoint/"+ IDENTIFIER + "/best_val_model.pth"
    res_path = "../test_res/" + IDENTIFIER + "_test.res"
    validation_batch_size = 64

    net = Net(in_shape = (3, CDISCOUNT_HEIGHT, CDISCOUNT_WIDTH), num_classes=CDISCOUNT_NUM_CLASSES)
    if use_cuda: net.cuda()

    if os.path.isfile(initial_checkpoint):
        print("=> loading checkpoint '{}'".format(initial_checkpoint))
        checkpoint = torch.load(initial_checkpoint)
        net.load_state_dict(checkpoint['state_dict'])  # load model weights from the checkpoint
        print("=> loaded checkpoint '{}'".format(initial_checkpoint))
    else:
        print("=> no checkpoint found at '{}'".format(initial_checkpoint))
        exit(0)

    transform_valid = transforms.Compose([transforms.Lambda(lambda x: valid_augment(x))])

    test_dataset = CDiscountTestDataset(csv_dir + test_data_filename, root_dir, transform=transform_valid)

    test_loader  = DataLoader(
                        test_dataset,
                        sampler = RandomSampler(test_dataset),
                        batch_size  = validation_batch_size,
                        drop_last   = True,
                        num_workers = 0,
                        pin_memory  = False)

    product_to_prediction_map = evaluate(net, test_loader)

    write_test_result(res_path, product_to_prediction_map)

    print('\nsucess!')
