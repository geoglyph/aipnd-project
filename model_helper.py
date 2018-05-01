import torch
from torch import nn
from torch import optim
from torch.autograd import Variable
from torchvision import datasets, transforms, models
from collections import OrderedDict
import utility
from PIL import Image


def create_model(arch, class_to_idx):
    # Load pretrained DenseNet model
    model = models.densenet121(pretrained=True)
    #model = models.vgg16(pretrained=True)

    # Freeze parameters so we don't backprop through them
    for param in model.parameters():
        param.requires_grad = False

    # Replace classifier, ensure output sizes matches number of classes
    # input_size = 224 * 224 * 3
    output_size = 102

    classifier = nn.Sequential(OrderedDict([
        ('fc1', nn.Linear(1024, 500)),
        ('relu', nn.ReLU()),
        ('fc2', nn.Linear(500, output_size)),
        ('output', nn.LogSoftmax(dim=1))
    ]))

    model.classifier = classifier

    # Set training parameters
    parameters = filter(lambda p: p.requires_grad, model.parameters())
    # optimizer = optim.SGD(parameters, lr=0.001)
    optimizer = optim.Adam(parameters, lr=0.001)
    # criterion = nn.CrossEntropyLoss()
    criterion = nn.NLLLoss()

    # Swap keys and items
    model.class_to_idx = {class_to_idx[k]: k for k in class_to_idx}

    return model, optimizer, criterion


def save_checkpoint(file_path, model, optimizer, total_epochs):
    state = {
        'epoch': total_epochs,
        'arch': 'densenet121',
        'state_dict': model.state_dict(),
        'optimizer': optimizer.state_dict(),
        'class_to_idx': model.class_to_idx
    }

    torch.save(state, file_path)

    print("Checkpoint Saved: '{}' (arch={} epochs={})".format(
        file_path, state['arch'], state['epoch']))


def load_checkpoint(file_path):
    # Get pretrained DenseNet model
    model = models.densenet121(pretrained=True)
    #model = models.vgg16(pretrained=True)

    # Replace classifier, ensure output sizes matches number of classes (102)
    classifier = nn.Sequential(OrderedDict([
        ('fc1', nn.Linear(1024, 500)),
        ('relu', nn.ReLU()),
        ('fc2', nn.Linear(500, 102)),
        ('output', nn.LogSoftmax(dim=1))
    ]))

    model.classifier = classifier

    # Load model state
    state = torch.load(file_path)
    model.load_state_dict(state['state_dict'])
    model.class_to_idx = state['class_to_idx']

    print("Checkpoint Loaded: '{}' (arch={} epochs={})".format(
        file_path, state['arch'], state['epoch']))

    return model


def validate(model, criterion, data_loader, use_gpu):
    # Put model in inference mode
    model.eval()

    accuracy = 0
    test_loss = 0
    for inputs, labels in iter(data_loader):

        # Set volatile to True so we don't save the history
        if use_gpu:
            inputs = Variable(inputs.float().cuda(), volatile=True)
            labels = Variable(labels.long().cuda(), volatile=True)
        else:
            inputs = Variable(inputs, volatile=True)
            labels = Variable(labels, volatile=True)

        output = model.forward(inputs)
        test_loss += criterion(output, labels).data[0]

        # Model's output is log-softmax,
        # take exponential to get the probabilities
        ps = torch.exp(output).data

        # Model's output is softmax
        # ps = output.data

        # Class with highest probability is our predicted class,
        equality = (labels.data == ps.max(1)[1])

        # Accuracy is number of correct predictions divided by all predictions, just take the mean
        accuracy += equality.type_as(torch.FloatTensor()).mean()

    return test_loss/len(data_loader), accuracy/len(data_loader)


def train(model, criterion, optimizer, epochs, training_data_loader, validation_data_loader, use_gpu):
    # Ensure model in training mode
    model.train()

    # Train the network using training data
    print_every = 40
    steps = 0

    for epoch in range(epochs):
        running_loss = 0

        # Get inputs and labels from training set
        for inputs, labels in iter(training_data_loader):
            steps += 1

            # Move tensors to GPU if available
            if use_gpu:
                inputs = Variable(inputs.float().cuda())
                labels = Variable(labels.long().cuda())
            else:
                inputs = Variable(inputs)
                labels = Variable(labels)

            # Set gradients to zero
            optimizer.zero_grad()

            # Forward pass to calculate logits
            output = model.forward(inputs)

            # Calculate loss (how far is prediction from label)
            loss = criterion(output, labels)

            # Backward pass to calculate gradients
            loss.backward()

            # Update weights using optimizer (add gradients to weights)
            optimizer.step()

            # Track the loss as we are training the network
            running_loss += loss.data[0]

            if steps % print_every == 0:
                test_loss, accuracy = validate(model,
                                               criterion,
                                               validation_data_loader,
                                               use_gpu)

                print("Epoch: {}/{} ".format(epoch+1, epochs),
                      "Training Loss: {:.3f} ".format(
                          running_loss/print_every),
                      "Test Loss: {:.3f} ".format(test_loss),
                      "Test Accuracy: {:.3f}".format(accuracy))

                running_loss = 0

                # Put model back in training mode
                model.train()


def predict(image_path, model, use_gpu, topk=5):
    ''' Predict the class (or classes) of an image using a trained deep learning model.
    '''
    # Put model in inference mode
    model.eval()

    image = Image.open(image_path)
    np_array = utility.process_image(image)
    tensor = torch.from_numpy(np_array)

    # Use GPU if available
    if use_gpu:
        var_inputs = Variable(tensor.float().cuda(), volatile=True)
    else:
        var_inputs = Variable(tensor, volatile=True)

    # Model is expecting 4d tensor, add another dimension
    var_inputs = var_inputs.unsqueeze(0)

    # Run image through model
    output = model.forward(var_inputs)

    # Model's output is log-softmax,
    # take exponential to get the probabilities
    ps = torch.exp(output).data.topk(topk)

    # Move results to CPU if needed
    probs = ps[0].cpu() if use_gpu else ps[0]
    classes = ps[1].cpu() if use_gpu else ps[1]

    # Map classes to indices
    mapped_classes = list()
    for label in classes.numpy()[0]:
        mapped_classes.append(model.class_to_idx[label])

    # Return results
    return probs.numpy()[0], mapped_classes