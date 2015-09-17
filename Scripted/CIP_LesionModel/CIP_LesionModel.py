import os, sys
import unittest
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging

import collections
import itertools

import numpy as np
import time
from FeatureWidgetHelperLib import FeatureExtractionLogic

# Add the CIP common library to the path if it has not been loaded yet
try:
    from CIP.logic.SlicerUtil import SlicerUtil
except Exception as ex:
    currentpath = os.path.dirname(os.path.realpath(__file__))
    # We assume that CIP_Common is in the development structure
    path = os.path.normpath(currentpath + '/../../Scripted/CIP_Common')
    if not os.path.exists(path):
        # We assume that CIP is a subfolder (Slicer behaviour)
        path = os.path.normpath(currentpath + '/CIP')
    sys.path.append(path)
    print("The following path was manually added to the PythonPath in CIP_LesionModel: " + path)
    from CIP.logic.SlicerUtil import SlicerUtil

from CIP.logic import Util
from CIP.ui import CaseReportsWidget

import FeatureWidgetHelperLib


#
# CIP_LesionModel
#
class CIP_LesionModel(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "CIP_LesionModel"
        self.parent.categories = SlicerUtil.CIP_ModulesCategory
        self.parent.dependencies = [SlicerUtil.CIP_ModuleName]
        self.parent.contributors = ["Jorge Onieva (jonieva@bwh.harvard.edu)", "Applied Chest Imaging Laboratory",
                                    "Brigham and Women's Hospital"]
        self.parent.helpText = """Segment and model a lung lesion"""
        self.parent.acknowledgementText = SlicerUtil.ACIL_AcknowledgementText


#
# CIP_LesionModelWidget
#

class CIP_LesionModelWidget(ScriptedLoadableModuleWidget):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None):
        """Widget constructor (existing module)"""
        ScriptedLoadableModuleWidget.__init__(self, parent)
        # from functools import partial
        # def onNodeAdded(self, caller, eventId, callData):
        #   """Node added to the Slicer scene"""
        #   if callData.GetClassName() == 'vtkMRMLMarkupsFiducialNode':
        #     self.onNewFiducialAdded(callData)
        #
        # self.onNodeAdded = partial(onNodeAdded, self)
        # self.onNodeAdded.CallDataType = vtk.VTK_OBJECT
        # slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)
        self.__storedColumnNames__ = None
        self.__initVars__()

    def __initVars__(self):
        self.logic = CIP_LesionModelLogic()
        self.__featureClasses__ = None
        self.selectedMainFeaturesKeys = set()
        self.selectedFeatureKeys = set()
        self.analysisResults = dict()

    @property
    def storedColumnNames(self):
        """ Column names that will be stored in the CaseReportsWidget
        :return:
        """
        if self.__storedColumnNames__ is None:
            self.__storedColumnNames__ = ["CaseId", "Date"]
            # Create a single features list with all the "child" features
            self.__storedColumnNames__.extend(itertools.chain.from_iterable(self.featureClasses.itervalues()))
            # for featureList in self.featureClassKeys.itervalues():
                # for feature in self.featureClassKeys[mainFeature]:
                #     self.__storedColumnNames__.append("{0}-{1}".format(mainFeature, feature))
        return self.__storedColumnNames__

    @property
    def featureClasses(self):
        """ Dictionary that contains all MainFeature-ChildFeatures values
        :return:
        """
        if self.__featureClasses__ is None:
            self.__featureClasses__ = collections.OrderedDict()
            # self.featureClassKeys["Node Information"] = ["Node"]
            self.__featureClasses__["First-Order Statistics"] = ["Voxel Count", "Gray Levels", "Energy", "Entropy",
                                                               "Minimum Intensity", "Maximum Intensity", "Mean Intensity",
                                                               "Median Intensity", "Range", "Mean Deviation",
                                                               "Root Mean Square", "Standard Deviation", "Skewness",
                                                               "Kurtosis", "Variance", "Uniformity"]
            self.__featureClasses__["Morphology and Shape"] = ["Volume mm^3", "Volume cc", "Surface Area mm^2",
                                                             "Surface:Volume Ratio", "Compactness 1", "Compactness 2",
                                                             "Maximum 3D Diameter", "Spherical Disproportion", "Sphericity"]
            self.__featureClasses__["Texture: GLCM"] = ["Autocorrelation", "Cluster Prominence", "Cluster Shade",
                                                      "Cluster Tendency", "Contrast", "Correlation", "Difference Entropy",
                                                      "Dissimilarity", "Energy (GLCM)", "Entropy(GLCM)", "Homogeneity 1",
                                                      "Homogeneity 2", "IMC1", "IDMN", "IDN", "Inverse Variance",
                                                      "Maximum Probability", "Sum Average", "Sum Entropy", "Sum Variance",
                                                      "Variance (GLCM)"]  # IMC2 missing
            self.__featureClasses__["Texture: GLRL"] = ["SRE", "LRE", "GLN", "RLN", "RP", "LGLRE", "HGLRE", "SRLGLE",
                                                      "SRHGLE", "LRLGLE", "LRHGLE"]
            self.__featureClasses__["Geometrical Measures"] = ["Extruded Surface Area", "Extruded Volume",
                                                             "Extruded Surface:Volume Ratio"]
            self.__featureClasses__["Renyi Dimensions"] = ["Box-Counting Dimension", "Information Dimension",
                                                         "Correlation Dimension"]
        return self.__featureClasses__


    def setup(self):
        """This is called one time when the module GUI is initialized
        """
        ScriptedLoadableModuleWidget.setup(self)

        self.semaphoreOpen = False
        self.timer = qt.QTimer()
        self.timer.timeout.connect(self.checkAndRefreshModels)
        self.lastRefreshValue = -5000  # Just a value out of range

        #######################
        # Main area
        mainAreaCollapsibleButton = ctk.ctkCollapsibleButton()
        mainAreaCollapsibleButton.text = "Main parameters"
        self.layout.addWidget(mainAreaCollapsibleButton)
        # Layout within the dummy collapsible button. See http://doc.qt.io/qt-4.8/layout.html for more info about layouts
        self.mainAreaLayout = qt.QFormLayout(mainAreaCollapsibleButton)

        self.inputVolumeSelector = slicer.qMRMLNodeComboBox()
        self.inputVolumeSelector.nodeTypes = ("vtkMRMLScalarVolumeNode", "")
        self.inputVolumeSelector.selectNodeUponCreation = True
        self.inputVolumeSelector.autoFillBackground = True
        self.inputVolumeSelector.addEnabled = False
        self.inputVolumeSelector.noneEnabled = False
        self.inputVolumeSelector.removeEnabled = False
        self.inputVolumeSelector.showHidden = False
        self.inputVolumeSelector.showChildNodeTypes = False
        self.inputVolumeSelector.setMRMLScene(slicer.mrmlScene)
        # self.volumeSelector.setStyleSheet("margin:0px 0 0px 0; padding:2px 0 2px 5px")
        self.mainAreaLayout.addRow("Select an input volume", self.inputVolumeSelector)

        self.addFiducialButton = ctk.ctkPushButton()
        self.addFiducialButton.text = "Add new seed"
        self.addFiducialButton.setFixedWidth(100)
        self.addFiducialButton.checkable = True
        self.addFiducialButton.enabled = False
        self.mainAreaLayout.addRow("Add seeds: ", self.addFiducialButton)


        # Container for the fiducials
        self.fiducialsContainerFrame = qt.QFrame()
        self.fiducialsContainerFrame.setLayout(qt.QVBoxLayout())
        self.mainAreaLayout.addWidget(self.fiducialsContainerFrame)

        # Example button with some common properties
        self.applySegmentationButton = ctk.ctkPushButton()
        self.applySegmentationButton.text = "Segment!"
        self.applySegmentationButton.toolTip = "This is the button toolTip"
        self.applySegmentationButton.setIcon(qt.QIcon("{0}/Reload.png".format(SlicerUtil.CIP_ICON_DIR)))
        self.applySegmentationButton.setIconSize(qt.QSize(20, 20))
        self.applySegmentationButton.setStyleSheet("font-weight:bold; font-size:12px")
        self.applySegmentationButton.setFixedWidth(200)
        self.mainAreaLayout.addRow("Segment the node: ", self.applySegmentationButton)

        # CLI progress bar
        self.progressBar = slicer.qSlicerCLIProgressBar()
        self.progressBar.visible = False
        self.mainAreaLayout.addWidget(self.progressBar)

        # Threshold
        self.distanceLevelSlider = qt.QSlider()
        self.distanceLevelSlider.orientation = 1  # Horizontal
        self.distanceLevelSlider.minimum = -50  # Ad-hoc value
        self.distanceLevelSlider.maximum = 50
        self.distanceLevelSlider.enabled = False
        self.mainAreaLayout.addRow("Select a threshold: ", self.distanceLevelSlider)

        # Different radius selection
        self.radiusFrame = qt.QFrame()
        self.radiusFrameLayout = qt.QGridLayout(self.radiusFrame)
        self.r15Checkbox = qt.QCheckBox()
        self.r15Checkbox.setText("15")
        self.radiusFrameLayout.addWidget(self.r15Checkbox, 0, 0)
        self.r20Checkbox = qt.QCheckBox()
        self.r20Checkbox.setText("20")
        self.radiusFrameLayout.addWidget(self.r20Checkbox, 1, 0)
        self.rOtherCheckbox = qt.QCheckBox()
        self.rOtherCheckbox.setText("Other")
        self.radiusFrameLayout.addWidget(self.rOtherCheckbox, 2, 0)
        self.otherRadiusTextbox = qt.QLineEdit()
        # self.otherRadiusTextbox.setFixedWidth(80)
        self.radiusFrameLayout.addWidget(self.otherRadiusTextbox, 2, 1)
        self.mainAreaLayout.addRow("Sphere radius (mm):", self.radiusFrame)

        # used to map feature class to a list of auto-generated feature checkbox widgets
        self.featureWidgets = collections.OrderedDict()
        for key in self.featureClasses.keys():
            self.featureWidgets[key] = list()

        self.HeterogeneityCADCollapsibleButton = ctk.ctkCollapsibleButton()
        self.HeterogeneityCADCollapsibleButton.text = "HeterogeneityCAD Features Selection"
        self.layout.addWidget(self.HeterogeneityCADCollapsibleButton)
        self.featuresHeterogeneityCADLayout = qt.QFormLayout(self.HeterogeneityCADCollapsibleButton)

        # auto-generate QTabWidget Tabs and QCheckBoxes (subclassed in FeatureWidgetHelperLib)
        self.tabsFeatureClasses = FeatureWidgetHelperLib.CheckableTabsWidget()
        self.featuresHeterogeneityCADLayout.addRow(self.tabsFeatureClasses)

        gridWidth, gridHeight = 3, 9
        for featureClass in self.featureClasses:
            # by default, features from the following features classes are checked:
            if featureClass in ["First-Order Statistics", "Morphology and Shape"]:
                # , "Texture: GLCM",
                #         "Texture: GLRL"]:
                check = True
            else:
                check = False
            tabFeatureClass = qt.QWidget()
            tabFeatureClass.setLayout(qt.QGridLayout())
            # featureList = (feature for feature in self.featureClassKeys[featureClass])
            gridLayoutCoordinates = ((row, col) for col in range(gridWidth) for row in range(gridHeight))
            for featureName in self.featureClasses[featureClass]:
                row, col = next(gridLayoutCoordinates, None)
                if featureName is None or row is None or col is None:
                    break
                featureCheckboxWidget = FeatureWidgetHelperLib.FeatureWidget()
                featureCheckboxWidget.Setup(featureName=featureName, checkStatus=check)

                tabFeatureClass.layout().addWidget(featureCheckboxWidget, row, col)
                self.featureWidgets[featureClass].append(featureCheckboxWidget)
            self.tabsFeatureClasses.addTab(tabFeatureClass, featureClass, self.featureWidgets[featureClass],
                                           checkStatus=check)

        self.tabsFeatureClasses.setCurrentIndex(1)

        # Convert the ordered dictionary to a flat list that contains all the features
        self.featureWidgetList = list(itertools.chain.from_iterable(self.featureWidgets.values()))
        self.featureMainCategoriesStringList = list(self.featureWidgets.keys())
        # or reduce(lambda x,y: x+y, self.featureWidgets.values())

        ########## Parameter options
        # add parameters for top-level feature classes
        # self.tabsFeatureClasses.addParameter("Geometrical Measures", "Extrusion Parameter 1")
        # self.tabsFeatureClasses.addParameter("Texture: GLCM", "GLCM Matrix Parameter 1")
        # self.tabsFeatureClasses.addParameter("Texture: GLRL", "GLRL Matrix Parameter 1")
        #
        # # compile dict of feature classes with parameter names and values
        # self.featureClassParametersDict = collections.OrderedDict()
        # for featureClassWidget in self.tabsFeatureClasses.getFeatureClassWidgets():
        #     featureClassName = featureClassWidget.getName()
        #     self.featureClassParametersDict[featureClassName] = collections.OrderedDict()
        #     self.updateFeatureClassParameterDict(0, featureClassWidget)
        #     for parameterName in featureClassWidget.widgetMenu.parameters:
        #         featureClassWidget.getParameterEditWindow(parameterName).connect('intValueChanged(int)',
        #                                                                          lambda intValue,
        #                                                                                 featureClassWidget=featureClassWidget: self.updateFeatureClassParameterDict(
        #                                                                              intValue, featureClassWidget))

        # add parameters for individual features
        # for featureWidget in self.heterogeneityFeatureWidgets:
        #     if featureWidget.getName() == "Voxel Count":
        #         featureWidget.addParameter("Example Parameter 1")
        #         featureWidget.addParameter("Example Parameter 2")
        #     if featureWidget.getName() == "Gray Levels":
        #         featureWidget.addParameter("Example Parameter 1-GL")
        #         featureWidget.addParameter("Example Parameter 2-GL")

        # compile dict of features with parameter names and values
        # self.featureParametersDict = collections.OrderedDict()
        # for featureWidget in self.heterogeneityFeatureWidgets:
        #     featureName = featureWidget.getName()
        #     self.featureParametersDict[featureName] = collections.OrderedDict()
        #     self.updateFeatureParameterDict(0, featureWidget)
        #     for parameterName in featureWidget.widgetMenu.parameters:
        #         featureWidget.getParameterEditWindow(parameterName).connect('intValueChanged(int)', lambda intValue,
        #                                                                                                    featureWidget=featureWidget: self.updateFeatureParameterDict(
        #             intValue, featureWidget))  # connect intvaluechanged signals to updateParamaterDict function
        ##########

        # Feature Buttons Frame and Layout
        self.featureButtonFrame = qt.QFrame(self.HeterogeneityCADCollapsibleButton)
        self.featureButtonFrame.setLayout(qt.QHBoxLayout())
        self.featuresHeterogeneityCADLayout.addRow(self.featureButtonFrame)

        # HeterogeneityCAD Apply Button
        self.HeterogeneityCADButton = qt.QPushButton("Analyze!", self.featureButtonFrame)
        self.HeterogeneityCADButton.toolTip = "Analyze input volume using selected Features."
        self.featureButtonFrame.layout().addWidget(self.HeterogeneityCADButton)



        # Reports widget
        self.reportsWidget = CaseReportsWidget(self.moduleName, columnNames=self.storedColumnNames,
                                               parent=self.featureButtonFrame)
        self.reportsWidget.setup()

        ######################
        # Anaysis area
        # analysisAreaCollapsibleButton = ctk.ctkCollapsibleButton()
        # analysisAreaCollapsibleButton.text = "Analysis"
        # self.layout.addWidget(analysisAreaCollapsibleButton)
        # # Layout within the dummy collapsible button. See http://doc.qt.io/qt-4.8/layout.html for more info about layouts
        # self.analysisAreaLayout = qt.QVBoxLayout(analysisAreaCollapsibleButton)
        #
        # self.histogramIntensityCheckBox = qt.QCheckBox()
        # self.histogramIntensityCheckBox.setText("Histogram statistics")
        # self.histogramIntensityCheckBox.setChecked(True)
        # self.analysisAreaLayout.addWidget(self.histogramIntensityCheckBox)
        #
        # self.localHistogramCheckBox = qt.QCheckBox()
        # self.localHistogramCheckBox.setText("Local histogram statistics (Parenchymal Volume)")
        # self.localHistogramCheckBox.setChecked(False)
        # self.analysisAreaLayout.addWidget(self.localHistogramCheckBox)
        #
        # self.texturalCheckBox = qt.QCheckBox()
        # self.texturalCheckBox.setText("Textural statistics")
        # self.texturalCheckBox.setChecked(False)
        # self.analysisAreaLayout.addWidget(self.texturalCheckBox)
        #
        # self.vasculaturityCheckBox = qt.QCheckBox()
        # self.vasculaturityCheckBox.setText("Vascularity statistics")
        # self.vasculaturityCheckBox.setChecked(False)
        # self.analysisAreaLayout.addWidget(self.vasculaturityCheckBox)
        #
        # self.radiusTextBox = qt.QLineEdit()
        # self.radiusTextBox.setText("30")
        # self.analysisAreaLayout.addWidget(self.radiusTextBox)
        #
        #
        # runAnalysisButton = ctk.ctkPushButton()
        # runAnalysisButton.setText("Run selected analysis")
        # runAnalysisButton.setFixedWidth(200)
        # # self.analysisAreaLayout.addWidget(runAnalysisButton)
        # self.featureButtonFrame.layout().addWidget(runAnalysisButton)

        ######################
        # Case navigator widget
        if SlicerUtil.isSlicerACILLoaded():
            # Add a case list navigator
            caseNavigatorCollapsibleButton = ctk.ctkCollapsibleButton()
            caseNavigatorCollapsibleButton.text = "Case navigator (advanced)"
            self.layout.addWidget(caseNavigatorCollapsibleButton)
            caseNavigatorAreaLayout = qt.QHBoxLayout(caseNavigatorCollapsibleButton)

            from ACIL.ui import CaseNavigatorWidget
            self.caseNavigatorWidget = CaseNavigatorWidget(parentModuleName="CIP_LesionModel",
                                                           parentContainer=caseNavigatorAreaLayout)


        ######################
        # Connections
        self.applySegmentationButton.connect('clicked()', self.__onApplySegmentationButtonClicked__)
        self.addFiducialButton.connect('clicked(bool)', self.__onAddFiducialButtonClicked__)

        self.inputVolumeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.__onInputVolumeChanged__)
        slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.EndCloseEvent, self.__onSceneClosed__)
        # self.distanceLevelSlider.connect('valueChanged(int)', self.onDistanceSliderChanged)
        # self.distanceLevelSlider.connect('sliderReleased()', self.onDistanceSliderChanged)

        # runAnalysisButton.connect("clicked()", self.__onRunAnalysisButtonClicked__)
        self.HeterogeneityCADButton.connect('clicked()', self.onAnalyzeButtonClicked)

        self.reportsWidget.addObservable(self.reportsWidget.EVENT_SAVE_BUTTON_CLICKED, self.onSaveReport)

        self.__refreshUI__()


        # self.fiducialsTableView = qt.QTableView()
        # self.fiducialsTableView.sortingEnabled = True
        # #self.tableView.minimumHeight = 550
        # # Unsuccesful attempts to autoscale the table
        # #self.tableView.maximumHeight = 800
        # policy = self.fiducialsTableView.sizePolicy
        # policy.setVerticalPolicy(qt.QSizePolicy.Expanding)
        # policy.setHorizontalPolicy(qt.QSizePolicy.Expanding)
        # policy.setVerticalStretch(0)
        # self.fiducialsTableView.setSizePolicy(policy)
        # # Hide the table until we have some volume loaded
        # self.fiducialsTableView.visible = False
        # # Create model for the table
        # self.fiducialsTableModel = qt.QStandardItemModel()
        # self.fiducialsTableView.setModel(self.fiducialsTableModel)
        # self.fiducialsTableView.verticalHeader().visible = False
        #
        # self.statsTableFrame.layout().addWidget(self.fiducialsTableView)
        #         >>> t = qt.QTableWidget()
        # >>> w = slicer.modules.CIP_LesionModelWidget
        # >>> w.mainAreaLayout.addWidget(t)
        # >>> t.setColumnCount(4)
        # >>> t.setHorizontalHeaderLabels(["","","Name",""])
        # >>> headerItem = t.horizontalHeaderItem(0)
        # >>> headerItem.setIcon(qt.QIcon(":/Icons/MarkupsSelected.png"))
        # >>> headerItem.setToolTip("Click in this column to select/deselect seeds")
        # >>> headerItem = t.horizontalHeaderItem(1)
        # >>> headerItem.setIcon(qt.QIcon(":/Icons/Small/SlicerLockUnlock.png"))
        # >>> t.setColumnWidth(0,30)
        # >>> t.setColumnWidth(1,30)
        # >>> t.setHorizontalHeaderLabels(["","","Name",""])
        # >>> headerItem.setIcon(qt.QIcon(":/Icons/Small/SlicerVisibleInvisible.png"))
        # >>> headerItem.setToolTip("Click in this column to show/hide markups in 2D and 3D")

    # def updateRow(self, index):
    #     #markupsNode = self.logic.getFiducialsListNode(self.inputVolumeSelector.currentNodeID)
    #     markupsNode = f
    #     selectedItem = qt.QTableWidgetItem()
    #     selectedItem.setCheckState(markupsNode.GetNthMarkupVisibility(index))
    #


    def enter(self):
        """This is invoked every time that we select this module as the active module in Slicer (not only the first time)"""
        if self.inputVolumeSelector.currentNodeID != '':
            self.logic.getFiducialsListNode(self.inputVolumeSelector.currentNodeID, self.__onFiducialsNodeModified__)
            self.logic.setActiveVolume(self.inputVolumeSelector.currentNodeID)

            if not self.timer.isActive() \
                    and self.logic.currentLabelmap is not None:  # Segmentation was already performed
                self.timer.start(500)

        self.__refreshUI__()

    def __refreshUI__(self):
        if self.inputVolumeSelector.currentNodeID != "":
            self.addFiducialButton.enabled = True
            self.addFiducialButton.toolTip = "Click and add a new seed in the volume"
        else:
            self.addFiducialButton.enabled = False
            self.addFiducialButton.toolTip = "Select a volume before adding any seed"
            self.__removeFiducialsFrames__()

        # Apply segmentation button allowed only if there is at least one seed
        if self.inputVolumeSelector.currentNodeID != "" and \
                        self.logic.getNumberOfFiducials(self.inputVolumeSelector.currentNodeID) > 0:
            self.applySegmentationButton.enabled = True
            self.applySegmentationButton.toolTip = "Run the segmentation algorithm"
        else:
            self.applySegmentationButton.enabled = False
            self.applySegmentationButton.toolTip = "Add at least one seed before running the algorithm"

        # Level slider active after running the segmentation algorithm
        if self.logic.cliOutputScalarNode is not None:
            self.distanceLevelSlider.enabled = True
            self.distanceLevelSlider.toolTip = "Move the slide to adjust the threshold for the model"
        else:
            self.distanceLevelSlider.enabled = False
            self.distanceLevelSlider.toolTip = "Please run the segmentation algorithm first"

        self.progressBar.visible = self.distanceLevelSlider.enabled

    def __removeFiducialsFrames__(self):
        """ Remove all the possible fiducial frames that can remain obsolete (for example after closing a scene)
        """
        while len(self.fiducialsContainerFrame.children()) > 1:
            self.fiducialsContainerFrame.children()[1].hide()
            self.fiducialsContainerFrame.children()[1].delete()

    def __setAddSeedsMode__(self, enabled):
        """ When enabled, the cursor will be enabled to add new fiducials that will be used for the segmentation
        :param enabled:
        :return:
        """
        applicationLogic = slicer.app.applicationLogic()
        if enabled:
            # print("DEBUG: entering __setAddSeedsMode__ - after enabled")
            if self.__validateInputVolumeSelection__():
                # Get the fiducials node
                fiducialsNodeList = self.logic.getFiducialsListNode(self.inputVolumeSelector.currentNodeID)
                # Set the cursor to draw fiducials
                markupsLogic = slicer.modules.markups.logic()
                markupsLogic.SetActiveListID(fiducialsNodeList)
                selectionNode = applicationLogic.GetSelectionNode()
                selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode")

                # Enable fiducials mode
                SlicerUtil.setFiducialsMode(True, False)
        else:
            # Regular cursor mode (not fiducials)
            SlicerUtil.setFiducialsMode(False)

    def addFiducialRow(self, fiducialsNode):
        """ Add a new row in the fiducials checkboxes section
        :param fiducialsNode:
        :return:
        """
        if self.semaphoreOpen:  # To avoid the problem of duplicated events
            frame = qt.QFrame()
            frameLayout = qt.QHBoxLayout()
            frame.setLayout(frameLayout)

            n = fiducialsNode.GetNumberOfFiducials() - 1

            # Checkbox to select/unselect
            selectFiducialsCheckbox = qt.QCheckBox()
            selectFiducialsCheckbox.checked = True
            selectFiducialsCheckbox.text = "Seed " + str(n + 1)
            selectFiducialsCheckbox.toolTip = "Check/uncheck to include/exclude this seed"
            selectFiducialsCheckbox.objectName = n
            frameLayout.addWidget(selectFiducialsCheckbox)
            selectFiducialsCheckbox.clicked.connect(lambda: self.__onFiducialCheckClicked__(selectFiducialsCheckbox))


            # Remove button?
            # fidButton = ctk.ctkPushButton()
            # n = fiducialsNode.GetNumberOfFiducials() - 1
            # fidButton.text = "Fiducial " + str(n)
            # #fidButton.objectName = displayNodeID
            # fidButton.objectName = n
            # fidButton.checkable = True
            # fidButton.clicked.connect(lambda: self.onFiducialButtonClicked(fidButton))

            # frame.layout().addWidget(fidButton)
            self.fiducialsContainerFrame.layout().addWidget(frame)
            self.addFiducialButton.checked = False

            self.semaphoreOpen = False

    def __validateInputVolumeSelection__(self):
        """ Check there is a valid input and/or output volume selected. Otherwise show a warning message
        :return: True if the validations are passed or False otherwise
        """
        inputVolumeId = self.inputVolumeSelector.currentNodeID
        if inputVolumeId == '':
            qt.QMessageBox.warning(slicer.util.mainWindow(), 'Warning', 'Please select an input volume')
            return False
        # if checkOutput:
        #     outputVolumeId = self.outputVolumeSelector.currentNodeID
        #     if outputVolumeId == '':
        #         qt.QMessageBox.warning(slicer.util.mainWindow(), 'Warning', 'Please select an output labelmap volume or create a new one')
        #         return False

        return True

    def checkAndRefreshModels(self, forceRefresh=False):
        """ Refresh the GUI if the slider value has changed since the last time"""
        if forceRefresh or self.lastRefreshValue != self.distanceLevelSlider.value:
            # Refresh slides
            # print("DEBUG: updating labelmaps with value:", float(self.distanceLevelSlider.value)/100)
            self.logic.updateModels(float(self.distanceLevelSlider.value) / 100)
            self.lastRefreshValue = self.distanceLevelSlider.value

            # Refresh visible windows
            SlicerUtil.refreshActiveWindows()

    def activateCurrentLabelmap(self):
        """ Display the right labelmap for the current background node if it exists"""
        # Set the current labelmap active
        selectionNode = slicer.app.applicationLogic().GetSelectionNode()
        selectionNode.SetReferenceActiveVolumeID(self.inputVolumeSelector.currentNodeID)

        selectionNode.SetReferenceActiveLabelVolumeID(self.logic.currentLabelmap.GetID())
        slicer.app.applicationLogic().PropagateVolumeSelection(0)

    # def calculateSelectedStatistics(self):
    #     # Get the distance map to calculate the required sphere
    #     self.logic.calculateCurrentDistanceMap()
    #     # if self.histogramIntensityCheckBox.checked:
    #     stats = self.logic.calculateCurrentHistogramIntensityStats()
    #     print("DEBUG: histogram statistics:")
    #     print(stats)

    def runAnalysis(self):
        # build list of features and feature classes based on what is checked by the user
        self.selectedMainFeaturesKeys = set()
        self.selectedFeatureKeys = set()

        for featureClass in self.featureWidgets:
            for widget in self.featureWidgets[featureClass]:
                if widget.checked:
                    self.selectedMainFeaturesKeys.add(featureClass)
                    self.selectedFeatureKeys.add(str(widget.text))

        if self.inputVolumeSelector.currentNode() is None:
            # TODO: disable the button until segmentation is done
            qt.QMessageBox.warning(slicer.util.mainWindow(), "Select a volume",
                                   "Please select and segment an input volume")
            return
        if self.logic.currentLabelmap is None:
            qt.QMessageBox.warning(slicer.util.mainWindow(), "Select a labelmap",
                                   "Please select and segment a labelmap volume")
            return
        if len(self.selectedFeatureKeys) == 0:
            qt.QMessageBox.information(slicer.util.mainWindow(), "Select a feature",
                                       "Please select at least one feature from the menu to calculate")
            return

        # Analysis for the volume and the nodule:
        keyName = self.inputVolumeSelector.currentNode().GetName()
        self.analysisResults[keyName] = FeatureExtractionLogic(self.logic.currentVolume, self.logic.currentVolumeArray,
                                             self.logic.currentLabelmapArray, self.featureClasses, self.selectedFeatureKeys)
        
        results = self.analysisResults[keyName].run()
        # self.FeatureVectors.append(nodeLogic.getFeatureVector())
        print("DEBUG: Obtained results for the nodule: ")
        print(results)
        
        # print("DEBUG: analyzing spheres...")
        # if self.r15Checkbox.checked:
        #     keyName = self.inputVolumeSelector.GetName() + "__r15"
        #     labelmap, labelmapArray = self.logic.getLabelmap(15)





        # self.populateStatistics(self.FeatureVectors)
        # self.saveButton.enabled = True

    def onSaveReport(self):
        """ Save the current values in a persistent csv file
        :return:
        """
        # TODO: include spheres and use "Date" column
        if self.analysisResults is not None:
            volumeName = self.inputVolumeSelector.currentNode().GetName()
            self.analysisResults[volumeName].AnalysisResultsDict["CaseId"] = volumeName
            self.reportsWidget.saveCurrentValues(**self.analysisResults[volumeName].AnalysisResultsDict)
            qt.QMessageBox.information(slicer.util.mainWindow(), 'Data saved', 'The data were saved successfully')


    ############
    # Events
    def __onInputVolumeChanged__(self, node):
        """ Input volume selector changed
        :param node: selected node
        """
        if node is not None:
            # Create the fiducials node in case it doesn't exist yet
            self.logic.getFiducialsListNode(node.GetID(), self.__onFiducialsNodeModified__)
            # Switch to the current node
            self.logic.setActiveVolume(node.GetID())

        elif self.timer.isActive():
            # Stop checking if there is no selected node
            self.timer.stop()

        self.__refreshUI__()

    def __onAddFiducialButtonClicked__(self, checked):
        """ Click the add fiducial button so that we set the cursor in fiducial mode
        :param checked:
        :return:
        """
        self.semaphoreOpen = True
        if not (self.__validateInputVolumeSelection__()):
            self.addFiducialButton.checked = False
            return

        self.__setAddSeedsMode__(checked)

    def __onApplySegmentationButtonClicked__(self):
        if self.__validateInputVolumeSelection__():
            result = self.logic.callNoduleSegmentationCLI(self.inputVolumeSelector.currentNodeID,
                                                          self.__onCLISegmentationFinished__)
            self.progressBar.setCommandLineModuleNode(result)
            self.progressBar.visible = True

            # Calculate meshgrid in parallel
            # self.logic.buildMeshgrid(self.inputVolumeSelector.currentNode())

    def __onFiducialsNodeModified__(self, nodeID, event):
        """ The active fiducials node has been modified because we added or removed a fiducial
        :param nodeID: Current node id
        :param event:
        """
        # print("DEBUG: Fiducials node modified.", nodeID)
        self.addFiducialRow(nodeID)
        self.__refreshUI__()

    # def onFiducialButtonClicked(self, button):
    #     print("Button pressed: ", button.objectName)
    #     n = int(button.objectName)
    #     logic = slicer.modules.markups.logic()
    #     fiducialsNode = slicer.util.getNode(logic.GetActiveListID())
    #     fiducialsNode.SetNthFiducialSelected(n, not button.checked)

    def __onFiducialCheckClicked__(self, checkBox):
        """ Click in one of the checkboxes that is associated with every fiducial
        :param checkBox: checkbox that has been clicked
        :return:
        """
        n = int(checkBox.objectName)
        logic = slicer.modules.markups.logic()
        fiducialsNode = slicer.util.getNode(logic.GetActiveListID())
        fiducialsNode.SetNthFiducialSelected(n, checkBox.checked)
        fiducialsNode.SetNthFiducialVisibility(n, checkBox.checked)
        # If selected, go to this markup
        if checkBox.checked:
            logic.JumpSlicesToNthPointInMarkup(fiducialsNode.GetID(), n, True)

    def __onCLISegmentationFinished__(self):
        """ Triggered when the CLI segmentation has finished the work.
        This is achieved because this is the function that we specify as a callback
        when calling the function "callCLI" in the logic class
        :return:
        """
        self.distanceLevelSlider.value = self.logic.defaultThreshold  # default
        self.activateCurrentLabelmap()

        range = self.logic.cliOutputScalarNode.GetImageData().GetScalarRange()

        self.distanceLevelSlider.minimum = range[0] * 100
        self.distanceLevelSlider.maximum = range[1] * 100
        self.distanceLevelSlider.value = self.logic.defaultThreshold

        self.checkAndRefreshModels(forceRefresh=True)
        self.__refreshUI__()

        # Start the timer that will refresh all the visualization nodes
        self.timer.start(500)

    # def __onRunAnalysisButtonClicked__(self):
    #     """ Calculate the selected statistics """
    #     self.calculateSelectedStatistics()

    def __onSceneClosed__(self, arg1, arg2):
        self.timer.stop()
        self.__initVars__()
        # Clean fiducials area
        self.__removeFiducialsFrames__()

    def exit(self):
        """This is invoked every time that we switch to another module (not only when Slicer is closed)."""
        # Disable chekbox of fiducials so that the cursor is not in "fiducials mode" forever if the
        # user leaves the module
        self.timer.stop()

    def cleanup(self):
        """This is invoked as a destructor of the GUI when the module is no longer going to be used"""
        self.timer.stop()

    def updateFeatureParameterDict(self, intValue, featureWidget):
        featureName = featureWidget.getName()
        self.featureParametersDict[featureName].update(featureWidget.getParameterDict())

    def updateFeatureClassParameterDict(self, intValue, featureClassWidget):
        featureClassName = featureClassWidget.getName()
        self.featureClassParametersDict[featureClassName].update(featureClassWidget.getParameterDict())

    def onAnalyzeButtonClicked(self):
        self.runAnalysis()



#############################
# CIP_LesionModelLogic
#############################
class CIP_LesionModelLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        self.cipMeasurements = CIP_Measurements()

        self.currentVolume = None  # Current active volume
        self.__currentVolumeArray__ = None  # Numpy array that represents the current volume
        self.currentLabelmap = None  # Current label map that contains the nodule segmentation for the current threshold (same size as the volume)
        self.__currentLabelmapArray__ = None  # Numpy array that represents the current label map
        self.cliOutputScalarNode = None  # Scalar volume that the CLI returns. This will be a cropped volume

        self.currentModelNodeId = None  # 3D model volume id
        self.defaultThreshold = 0  # Default threshold for the map distance used in the nodule segmentation
        self.onCLISegmentationFinishedCallback = None

        # self.origin = None                  # Current origin (centroid of the nodule)
        self.currentDistanceMap = None  # Current distance map from the specified origin

        self.spheresLabelmaps = dict()

    @property
    def currentModelNode(self):
        if self.currentModelNodeId is None:
            return None
        return slicer.util.getNode(self.currentModelNodeId)

    @property
    def currentVolumeArray(self):
        if self.__currentVolumeArray__ is None and self.currentVolume is not None:
            self.__currentVolumeArray__ = slicer.util.array(self.currentVolume.GetName())
        return self.__currentVolumeArray__

    @currentVolumeArray.setter
    def currentVolumeArray(self, value):
        self.__currentVolumeArray__ = value

    @property
    def currentLabelmapArray(self):
        if self.__currentLabelmapArray__ is None and self.currentLabelmap is not None:
            self.__currentLabelmapArray__ = slicer.util.array(self.currentLabelmap.GetName())
        return self.__currentLabelmapArray__

    @currentLabelmapArray.setter
    def currentLabelmapArray(self, value):
        self.__currentLabelmapArray__ = value

    ##############################
    # General volume / fiducials methods
    ##############################
    def setActiveVolume(self, volumeID):
        """ Set the current volume as active and try to load the preexisting associated structures
        (labelmaps, CLI segmented nodes, numpy arrays...)
        :param volumeID:
        :return:
        """
        self.currentVolume = slicer.util.getNode(volumeID)

        # Switch the fiducials node
        fiducialsNode = self.getFiducialsListNode(volumeID)
        markupsLogic = slicer.modules.markups.logic()
        markupsLogic.SetActiveListID(fiducialsNode)

        # Search for preexisting labelmap
        labelmapName = self.currentVolume.GetID() + '_lm'
        self.currentLabelmap = slicer.util.getNode(labelmapName)
        segmentedNodeName = self.currentVolume.GetID() + '_segmentedlm'
        self.cliOutputScalarNode = slicer.util.getNode(segmentedNodeName)

    def __createFiducialsListNode__(self, fiducialsNodeName, onModifiedCallback=None):
        """ Create a new fiducials list node for the current volume
        :param fiducialsNodeName: fiducials node name that will be created
        :param onModifiedCallback: function that will be connected to node's "ModifiedEvent"
        :return: True if the node was created or False if it already existed
        """
        markupsLogic = slicer.modules.markups.logic()
        fiducialsNode = slicer.util.getNode(fiducialsNodeName)
        if fiducialsNode is not None:
            return False  # Node already created

        # Create new fiducials node
        fiducialListNodeID = markupsLogic.AddNewFiducialNode(fiducialsNodeName, slicer.mrmlScene)
        fiducialsNode = slicer.util.getNode(fiducialListNodeID)
        # Make the new fiducials node the active one
        markupsLogic.SetActiveListID(fiducialsNode)
        # Hide any text from all the fiducials
        fiducialsNode.SetMarkupLabelFormat('')
        displayNode = fiducialsNode.GetDisplayNode()
        # displayNode.SetColor([1,0,0])
        displayNode.SetSelectedColor([1, 0, 0])
        displayNode.SetGlyphScale(4)
        displayNode.SetGlyphType(8)  # Diamond shape (I'm so cool...)

        # Add observer when specified
        if onModifiedCallback is not None:
            # The callback function will be invoked when the fiducials node is modified
            fiducialsNode.AddObserver("ModifiedEvent", onModifiedCallback)

        # Node created succesfully
        return True

    def getFiducialsListNode(self, volumeId, onModifiedCallback=None):
        """ Get the current fiducialsListNode for the specified volume, and creates it in case
        it doesn't exist yet.
        :param volumeId: fiducials list will be connected to this volume
        :return: the fiducials node or None if something fails
        """
        if volumeId == "":
            return None

        markupsLogic = slicer.modules.markups.logic()

        # Check if the node already exists
        fiducialsNodeName = volumeId + '_fiducialsNode'

        fiducialsNode = slicer.util.getNode(fiducialsNodeName)
        if fiducialsNode is not None:
            if onModifiedCallback is not None:
                fiducialsNode.AddObserver("ModifiedEvent", onModifiedCallback)
            return fiducialsNode

        # Create new fiducials node
        if self.__createFiducialsListNode__(fiducialsNodeName, onModifiedCallback):
            return slicer.util.getNode(fiducialsNodeName)  # return the created node

        return None  # The process failed

    def getNumberOfFiducials(self, volumeId):
        """ Get the number of fiducials currently set for this volume
        :param volumeId:
        :return:
        """
        fid = self.getFiducialsListNode(volumeId)
        if fid:
            return fid.GetNumberOfMarkups()
        return None  # Error

    ##############################
    # CLI Nodule segmentation
    ##############################
    def callNoduleSegmentationCLI(self, inputVolumeID, onCLISegmentationFinishedCallback=None):
        """ Invoke the Lesion Segmentation CLI for the specified volume and fiducials.
        Note: the fiducials will be retrieved directly from the scene
        :param inputVolumeID:
        :return:
        """
        # Try to load preexisting structures
        self.setActiveVolume(inputVolumeID)

        if self.cliOutputScalarNode is None:
            # Create the scalar node that will work as the CLI output
            self.cliOutputScalarNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLScalarVolumeNode")
            segmentedNodeName = self.currentVolume.GetID() + '_segmentedlm'
            self.cliOutputScalarNode.SetName(segmentedNodeName)
            slicer.mrmlScene.AddNode(self.cliOutputScalarNode)

        parameters = {}
        print("DEBUG: Calling CLI...")
        parameters["inputImage"] = inputVolumeID
        parameters["outputLevelSet"] = self.cliOutputScalarNode
        parameters["seedsFiducials"] = self.getFiducialsListNode(inputVolumeID)
        parameters["fullSizeOutput"] = True
        self.invokedCLI = False  # Semaphore to avoid duplicated events

        module = slicer.modules.generatelesionsegmentation
        result = slicer.cli.run(module, None, parameters)

        # Observer when the state of the process is modified
        result.AddObserver('ModifiedEvent', self.__onNoduleSegmentationCLIStateUpdated__)
        # Function that will be invoked when the CLI finishes
        self.onCLISegmentationFinishedCallback = onCLISegmentationFinishedCallback

        return result

    def __onNoduleSegmentationCLIStateUpdated__(self, caller, event):
        """ Event triggered when the CLI status changes
        :param caller:
        :param event:
        :return:
        """
        if caller.IsA('vtkMRMLCommandLineModuleNode') \
                and not self.invokedCLI:  # Semaphore to avoid duplicated events
            if caller.GetStatusString() == "Completed":
                self.invokedCLI = True
                self.__processNoduleSegmentationCLIResults__()
            elif caller.GetStatusString() == "Completed with errors":
                # TODO: print current parameters with caller.GetParameterDefault()
                raise Exception("The Nodule Segmentation CLI failed")

    def __processNoduleSegmentationCLIResults__(self):
        """ Method called once that the cli has finished the process.
        Create a new labelmap (currentLabelmap) and a model node with the result of the process.
        It also creates a numpy array associated with the labelmap (currentLabelmapArray)
        """
        print("DEBUG: processing results from process Nodule CLI...")
        # Create vtk filters
        self.thresholdFilter = vtk.vtkImageThreshold()
        self.thresholdFilter.SetInputData(self.cliOutputScalarNode.GetImageData())
        self.thresholdFilter.SetReplaceOut(True)
        self.thresholdFilter.SetOutValue(0)  # Value of the background
        self.thresholdFilter.SetInValue(1)  # Value of the segmented nodule

        labelmapName = self.currentVolume.GetID() + '_lm'
        self.currentLabelmap = slicer.util.getNode(labelmapName)
        if self.currentLabelmap is None:
            # Create a labelmap with the same dimensions that the ct volume
            self.currentLabelmap = SlicerUtil.getLabelmapFromScalar(self.cliOutputScalarNode, labelmapName)

        self.currentLabelmap.SetImageDataConnection(self.thresholdFilter.GetOutputPort())
        self.marchingCubesFilter = vtk.vtkMarchingCubes()
        # self.marchingCubesFilter.SetInputConnection(self.thresholdFilter.GetOutputPort())
        self.marchingCubesFilter.SetInputData(self.cliOutputScalarNode.GetImageData())
        self.marchingCubesFilter.SetValue(0, self.defaultThreshold)

        newNode = self.currentModelNode is None
        if newNode:
            # Create the result model node and connect it to the pipeline
            modelsLogic = slicer.modules.models.logic()
            currentModelNode = modelsLogic.AddModel(self.marchingCubesFilter.GetOutput())
            self.currentModelNodeId = currentModelNode.GetID()
            # Create a DisplayNode and associate it to the model, in order that transformations can work properly
            displayNode = slicer.vtkMRMLModelDisplayNode()
            slicer.mrmlScene.AddNode(displayNode)
            currentModelNode.AddAndObserveDisplayNodeID(displayNode.GetID())

        if self.onCLISegmentationFinishedCallback is not None:
            # Delegate the responsibility of updating the models with a chosen threshold (regular case)
            self.onCLISegmentationFinishedCallback()
        else:
            self.updateModels(self.defaultThreshold)  # Use default threshold value

        if newNode:
            # Align the model with the segmented labelmap applying a transformation
            transformMatrix = vtk.vtkMatrix4x4()
            self.currentLabelmap.GetIJKToRASMatrix(transformMatrix)
            currentModelNode.ApplyTransformMatrix(transformMatrix)
            # Center the 3D view in the seed/s
            layoutManager = slicer.app.layoutManager()
            threeDWidget = layoutManager.threeDWidget(0)
            threeDView = threeDWidget.threeDView()
            threeDView.resetFocalPoint()

    def updateModels(self, newThreshold):
        """ Modify the threshold for the current volume (update the models)
        :param newThreshold: new threshold (all the voxels below this threshold will be considered nodule)
        """
        print("DEBUG: updating models....")
        self.thresholdFilter.ThresholdByUpper(newThreshold)
        self.thresholdFilter.Update()
        self.marchingCubesFilter.SetValue(0, newThreshold)
        self.marchingCubesFilter.Update()
        self.currentLabelmapArray = slicer.util.array(self.currentLabelmap.GetName())

    def calculateCurrentDistanceMap(self):
        """ Calculate the distance map to the centroid for the current labelmap volume.
        To that end, we have to calculate first the centroid.
        Please note the results could be cached
        :return:
        """
        # lmNode2 = slicer.util.getNode("Sphere")
        # if lmNode2 is None:
        #     lmNode2 = SlicerUtil.cloneVolume(self.currentLabelmap, "Sphere")
        # array = slicer.util.array(lmNode2.GetName())
        if self.currentDistanceMap is None:
            centroid = self.cipMeasurements.centroid(self.currentLabelmapArray)
            # Calculate the distance map for the specified origin
            self.currentDistanceMap = self.cipMeasurements.get_current_distance_map(self.currentVolume, centroid)
            # array[self.currentDistanceMap <= radius ** 2] = 2
            # lmNode2.GetImageData().Modified()

    def calculateCurrentHistogramIntensityStats(self):
        """ Calculate the current histogram statistics and also get the current
        numpy arrays for volume and labelmap
        :return:
        """
        if self.currentVolumeArray is None:
            self.currentVolumeArray = slicer.util.array(self.currentVolume.GetName())

        if self.currentLabelmapArray is None:
            self.currentLabelmapArray = slicer.util.array(self.currentLabelmap.GetName())

        spacing = self.currentVolume.GetSpacing()
        stats = self.cipMeasurements.histogram_intensity_basic_statistics_array(self.currentVolumeArray,
                                                                                self.currentLabelmapArray, spacing)
        return stats

    def getSphereLabelMap(self, radius):
        """ Get a labelmap that contains a sphere centered in the nodule centroid, with radius "radius" and that
        EXCLUDES the nodule itself.
        If the results are not cached, this method creates the volume and calculates the labelmap
        :param radius:
        :return:
        """
        pass


        # def __processCLIResults__(self):
        #     """ Method called once that the cli has finished the process.
        #     Create a new labelmap with the result of the process
        #     """
        #     print("DEBUG: processing results from CLI...")
        #     volumesLogic = slicer.modules.volumes.logic()
        #
        #     # Create a numpy array for the processed result
        #     self.cliOutputArray =  slicer.util.array(self.cliOutputScalarNode.GetName())
        #
        #     # Remove the current labelmap if it already existed
        #     slicer.mrmlScene.RemoveNode(self.currentLabelmap)
        #     # Create a new labelmap for the segmented volume (we have to adapt it to the new labelmap type)
        #     labelmapName = self.currentVolume.GetID() + '_lm'
        #     self.currentLabelmap = Util.convertScalarToLabelmap(self.cliOutputScalarNode, labelmapName)
        #     # Get a numpy array to work with the labelmap
        #     self.currentLabelmapArray = slicer.util.array(labelmapName)
        #
        #     #print("DEBUG: labelmap array created. Shape: ", self.currentLabelmapArray.shape)
        #     # Model render
        #     logic = slicer.modules.volumerendering.logic()
        #     displayNode = logic.GetFirstVolumeRenderingDisplayNode(self.currentLabelmap)
        #     if displayNode is None:
        #         # Create the rendering infrastructure
        #         displayNode = logic.CreateVolumeRenderingDisplayNode()
        #         slicer.mrmlScene.AddNode(displayNode)
        #         logic.UpdateDisplayNodeFromVolumeNode(displayNode, self.currentLabelmap)
        #
        #     # Invoke the callback if specified
        #     if self.onCLISegmentationFinishedCallback is not None:
        #         self.onCLISegmentationFinishedCallback()

        # def updateLabelmap(self, newValue):
        #     """ Update the labelmap representing the segmentation. Depending on the value the
        #     user will see a "bigger" or "smaller" segmentation.
        #     This is based on numpy modification.

        #     if self.currentLabelmap:
        #         self.currentLabelmapArray[:] = 0
        #         self.currentLabelmapArray[self.cliOutputArray >= newValue] = 1
        #         self.currentLabelmap.GetImageData().Modified()

        # def createAndAddToSceneWrapperScalarNode(self, bigNode, smallNode):
        #     # Clone the big node
        #     vl = slicer.modules.volumes.logic()
        #     copyVol = vl.CloneVolume(slicer.mrmlScene, bigNode, bigNode.GetName() + "_copy")
        #     # Get the associated numpy array
        #     copyArray = slicer.util.array(copyVol.GetName())
        #     # Reset all the values
        #     copyArray[:] = 0
        #     # Get the associated numpy array for the small node
        #     smallArray = slicer.util.array(smallNode.GetName())
        #
        #     # Calculate the offsets
        #     offset = [copyArray.shape[0]-smallArray.shape[0], copyArray.shape[1]-smallArray.shape[1], copyArray.shape[2]-smallArray.shape[2]]
        #


# import numpy as np
# from CIP.logic import Util

class CIP_Measurements(object):
    """ Class that will be used to perform all the measurements and other operations in Nodules module.
    The operations may be reused by another modules.
    """

    def __init__(self):
        pass

    def centroid(self, numpyArray, labelId=1):
        """ Calculate the coordinates of a centroid for a concrete labelId (default=1)
        :param numpyArray: numpy array
        :param labelId: label id (dafault = 1)
        :return: numpy array with the coordinates (int format)
        """
        mean = np.mean(np.where(numpyArray == labelId), axis=1)
        return np.asarray(np.round(mean, 0), np.int)

    def get_current_distance_map(self, volume, origin, max_radius=30):
        """ Calculate a distance map from the origin (zyx coords) in the specified volume
        :param volume: vtk scalar volume (it can be a labelmap too)
        :param origin: coordinates of the origin (ijk)
        :return:
        """
        # Get the dimensions of the volume
        dims = volume.GetImageData().GetDimensions()
        dims = (dims[2], dims[1], dims[0])
        # Get the spacing of the volume (it must be "reversed" compared to the dimensions ob the object)
        spacing = volume.GetSpacing()

        dm = Util.get_distance_map_fast_marching(dims, spacing, origin, stopping_value=max_radius)
        # Return a squared distance to make it easier to filter by radius
        return dm * dm

    def histogram_intensity_basic_statistics_array(self, intensity_array, labelmap_array, spacing, label=1):
        """ Get a dictionary with basic statistics based on histogram (average, max, min, etc.)
        :param intensity_array: numpy array for the volume
        :param labelmap_array: numpy array for the labelmap volume
        :param spacing: 3 spacings
        :param label: label to analyze (default: 1)
        :return: dictionary with the following key-values:
            - count (total pixel count)
            - volume (total volume in mm3)
            - mean (intensity)
            - max (intensity)
            - min (intensity)
            - std (intensity)
            - median (intensity)
        """
        # Get the numpy arrays
        result = {
            "count": 0,
            "volume": 0,
            "mean": 0,
            "min": 0,
            "max": 0,
            "std": 0,
            "median": 0
        }

        # Get all pixels with this label
        t = (labelmap_array == label)
        count = t.sum()
        result["count"] = count

        if count == 0:
            # If all the values are 0, it is not neccesary to calculate anything else (just return an empty object)
            return result

        # Perform the calulations.
        filtered = intensity_array[t]
        result["volume"] = count * spacing[0] * spacing[1] * spacing[2]
        result["mean"] = filtered.mean()
        result["min"] = filtered.min()
        result["max"] = filtered.max()
        result["std"] = filtered.std()
        result["median"] = np.median(filtered)

        return result

    def histogram_intensity_basic_statistics(self, intensity_volume, labelmap_volume, label=1,
                                             return_numpy_arrays=False):
        """ Get a dictionary with basic statistics based on histogram (average, max, min, etc.)
        :param intensity_volume: intensity vtk scalar volume
        :param labelmap_volume: labelmap volume
        :param label: label to analyze (default: 1)
        :param return_numpy_arrays: when True, return the numpy arrays that represent the intensity and labelmap volumes
        :return: dictionary with the following key-values:
            - count (total pixel count)
            - volume (total volume in mm3)
            - average (intensity)
            - max (intensity)
            - min (intensity)
            - std (intensity)
            - median (intensity)

            When "return_numpy_arrays==True", it also returns the intensity and labelmap numpy arrays corresponding
            the volumes
        """
        # Get the numpy arrays
        intensity_array = Util.vtk_to_numpy_array(intensity_volume.GetImageData())
        labelmap_array = Util.vtk_to_numpy_array(labelmap_volume.GetImageData())
        spacing = intensity_volume.GetSpacing()
        results = self.histogram_intensity_basic_statistics_array(intensity_array, labelmap_array, spacing, label)

        if return_numpy_arrays:
            return results, intensity_array, labelmap_array
        else:
            return results


class CIP_LesionModelTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """ Do whatever is needed to reset the state - typically a scene clear will be enough.
        """
        slicer.mrmlScene.Clear(0)

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_CIP_LesionModel_PrintMessage()

    def test_CIP_LesionModel_PrintMessage(self):
        self.delayDisplay("Starting the test")
        # logic = CIP_LesionModelLogic()
        # myMessage = "Print this test message in console"
        # logging.info("Starting the test with this message: " + myMessage)
        # expectedMessage = "I have printed this message: " + myMessage
        # logging.info("The expected message would be: " + expectedMessage)
        # responseMessage = logic.printMessage(myMessage)
        # logging.info("The response message was: " + responseMessage)
        # self.assertTrue(responseMessage == expectedMessage)
        # self.delayDisplay('Test passed!')
        # t = unittest.TestCase()
        self.fail("Test not implemented yet")
